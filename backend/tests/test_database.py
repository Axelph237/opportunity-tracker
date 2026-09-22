"""Schema creation, additive migrations, seed idempotency, FK cascades."""

from __future__ import annotations

import sqlite3

import database


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_init_db_creates_all_tables(db_path):
    with database.get_db() as conn:
        tables = _table_names(conn)
    expected = {
        "sources", "opportunities", "applications", "source_proposals",
        "scrape_logs", "walten_sessions", "walten_messages", "excluded_urls",
        "resume_advice", "role_analyses", "settings",
    }
    assert expected <= tables


def test_init_db_seeds_sources_and_settings(db_path):
    with database.get_db() as conn:
        source_count = conn.execute("SELECT COUNT(*) c FROM sources").fetchone()["c"]
        settings = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}
    assert source_count == len(database.SEED_SOURCES)
    assert settings["onboarding_complete"] == "0"
    assert "cron_schedule" in settings


def test_seed_sources_is_idempotent(db_path):
    with database.get_db() as conn:
        before = conn.execute("SELECT COUNT(*) c FROM sources").fetchone()["c"]
        before_max_id = conn.execute("SELECT MAX(id) m FROM sources").fetchone()["m"]
        inserted_again = database.seed_sources(conn)
        after = conn.execute("SELECT COUNT(*) c FROM sources").fetchone()["c"]
        after_max_id = conn.execute("SELECT MAX(id) m FROM sources").fetchone()["m"]
    assert inserted_again == 0
    assert before == after
    # Re-running seeding must not have inflated the AUTOINCREMENT counter.
    assert before_max_id == after_max_id


def test_seed_settings_does_not_clobber_user_changes(db_path):
    database.set_setting("model", "opus")
    with database.get_db() as conn:
        database.seed_settings(conn)
    assert database.get_setting("model") == "opus"


def test_migration_adds_new_columns_and_preserves_data(tmp_path, monkeypatch):
    """Simulate a database created by an earlier version of the schema.

    Older-shaped tables are missing every column the `_migrate` dict adds
    later (last_status/last_error on sources, strong_match/is_active/etc. on
    opportunities, ...). `init_db()` must add them without touching existing
    rows.
    """
    path = tmp_path / "old.db"
    monkeypatch.setattr(database, "DB_PATH", path)

    old_schema = """
    CREATE TABLE sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        url TEXT NOT NULL UNIQUE,
        type TEXT NOT NULL,
        scrape_method TEXT NOT NULL DEFAULT 'html',
        active INTEGER NOT NULL DEFAULT 1,
        last_scraped TEXT,
        date_added TEXT NOT NULL DEFAULT (datetime('now')),
        added_by TEXT NOT NULL DEFAULT 'user'
    );
    CREATE TABLE opportunities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        organization TEXT NOT NULL,
        type TEXT NOT NULL,
        location TEXT,
        remote INTEGER DEFAULT 0,
        url TEXT NOT NULL UNIQUE,
        description TEXT,
        deadline TEXT,
        date_found TEXT NOT NULL DEFAULT (datetime('now')),
        source_id INTEGER REFERENCES sources(id),
        relevance_score REAL,
        experience_level TEXT
    );
    CREATE TABLE applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
        status TEXT NOT NULL DEFAULT 'bookmarked',
        date_bookmarked TEXT DEFAULT (datetime('now')),
        date_applied TEXT,
        notes TEXT,
        last_updated TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE role_analyses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        generated_at TEXT NOT NULL DEFAULT (datetime('now')),
        scope TEXT,
        opportunity_count INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE walten_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        phase TEXT NOT NULL DEFAULT 'plan',
        content TEXT
    );
    """
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(old_schema)
    conn.execute(
        "INSERT INTO sources (name, url, type) VALUES ('Old Source', 'https://old.example/jobs', 'job_board')"
    )
    conn.execute(
        "INSERT INTO opportunities (title, organization, type, url) "
        "VALUES ('Old Listing', 'Old Org', 'job', 'https://old.example/jobs/1')"
    )
    conn.execute("INSERT INTO applications (opportunity_id, status) VALUES (1, 'applied')")
    conn.commit()
    conn.close()

    database.init_db()

    with database.get_db() as conn:
        source_cols = database._column_names(conn, "sources")
        opportunity_cols = database._column_names(conn, "opportunities")
        application_cols = database._column_names(conn, "applications")
        role_analysis_cols = database._column_names(conn, "role_analyses")
        walten_message_cols = database._column_names(conn, "walten_messages")

        source_row = conn.execute("SELECT * FROM sources WHERE id = 1").fetchone()
        opportunity_row = conn.execute("SELECT * FROM opportunities WHERE id = 1").fetchone()
        application_row = conn.execute("SELECT * FROM applications WHERE id = 1").fetchone()

    for column in ("search_query", "last_result_count", "pending_approval", "notes", "last_status", "last_error"):
        assert column in source_cols
    for column in ("relevance_summary", "skill_matches", "tags", "notes", "strong_match", "is_active", "last_seen"):
        assert column in opportunity_cols
    for column in ("deadline_override", "cover_letter_notes", "contacts"):
        assert column in application_cols
    assert "edited_at" in role_analysis_cols
    assert {"snapshot_sha", "snapshot_tree"} <= walten_message_cols

    # Original rows survive untouched.
    assert source_row["name"] == "Old Source"
    assert source_row["url"] == "https://old.example/jobs"
    assert source_row["last_status"] is None
    assert opportunity_row["title"] == "Old Listing"
    assert application_row["status"] == "applied"

    # The seed data and settings ran too, since init_db() also seeds on an
    # existing (migrated) database.
    with database.get_db() as conn:
        seeded = conn.execute("SELECT COUNT(*) c FROM sources").fetchone()["c"]
        settings_count = conn.execute("SELECT COUNT(*) c FROM settings").fetchone()["c"]
    assert seeded == 1 + len(database.SEED_SOURCES)
    assert settings_count == len(database.DEFAULT_SETTINGS)


def test_migration_is_a_noop_on_a_fresh_database(db_path):
    """Running _migrate against a database created by the current schema adds nothing."""
    with database.get_db() as conn:
        before = {
            table: sorted(database._column_names(conn, table))
            for table in ("sources", "opportunities", "applications", "role_analyses", "walten_messages")
        }
        database._migrate(conn)
        after = {
            table: sorted(database._column_names(conn, table))
            for table in ("sources", "opportunities", "applications", "role_analyses", "walten_messages")
        }
    assert before == after


def test_application_cascade_deletes_with_opportunity(db_path):
    with database.get_db() as conn:
        conn.execute(
            "INSERT INTO opportunities (title, organization, type, url) "
            "VALUES ('T', 'Org', 'job', 'https://example.com/j/1')"
        )
        opportunity_id = conn.execute("SELECT id FROM opportunities WHERE url = 'https://example.com/j/1'").fetchone()["id"]
        conn.execute("INSERT INTO applications (opportunity_id, status) VALUES (?, 'bookmarked')", (opportunity_id,))
        conn.execute(
            "INSERT INTO resume_advice (opportunity_id, fit_summary) VALUES (?, 'ok')", (opportunity_id,)
        )

    with database.get_db() as conn:
        applications_before = conn.execute("SELECT COUNT(*) c FROM applications").fetchone()["c"]
        advice_before = conn.execute("SELECT COUNT(*) c FROM resume_advice").fetchone()["c"]
        conn.execute("DELETE FROM opportunities WHERE id = ?", (opportunity_id,))

    with database.get_db() as conn:
        applications_after = conn.execute("SELECT COUNT(*) c FROM applications").fetchone()["c"]
        advice_after = conn.execute("SELECT COUNT(*) c FROM resume_advice").fetchone()["c"]

    assert applications_before == 1 and applications_after == 0
    assert advice_before == 1 and advice_after == 0


def test_walten_message_cascade_deletes_with_session(db_path):
    with database.get_db() as conn:
        conn.execute("INSERT INTO walten_sessions (title) VALUES ('S')")
        session_id = conn.execute("SELECT id FROM walten_sessions WHERE title = 'S'").fetchone()["id"]
        conn.execute(
            "INSERT INTO walten_messages (session_id, role, phase, content) VALUES (?, 'user', 'plan', 'hi')",
            (session_id,),
        )
        conn.execute("DELETE FROM walten_sessions WHERE id = ?", (session_id,))
        remaining = conn.execute(
            "SELECT COUNT(*) c FROM walten_messages WHERE session_id = ?", (session_id,)
        ).fetchone()["c"]
    assert remaining == 0


def test_exclude_url_and_excluded_urls_roundtrip(db_path):
    database.exclude_url("https://example.com/dead", "deleted", "removed by user")
    urls = database.excluded_urls()
    assert "https://example.com/dead" in urls


def test_excluded_urls_dead_link_expires_after_recheck_window(db_path):
    with database.get_db() as conn:
        conn.execute(
            "INSERT INTO excluded_urls (url, reason, excluded_at) VALUES (?, 'dead_link', datetime('now', '-30 days'))",
            ("https://example.com/stale-dead",),
        )
        conn.execute(
            "INSERT INTO excluded_urls (url, reason, excluded_at) VALUES (?, 'dead_link', datetime('now'))",
            ("https://example.com/fresh-dead",),
        )
        conn.execute(
            "INSERT INTO excluded_urls (url, reason, excluded_at) VALUES (?, 'deleted', datetime('now', '-30 days'))",
            ("https://example.com/deleted-forever",),
        )
    urls = database.excluded_urls()
    assert "https://example.com/stale-dead" not in urls
    assert "https://example.com/fresh-dead" in urls
    assert "https://example.com/deleted-forever" in urls


def test_get_set_all_settings(db_path):
    database.set_setting("model", "opus")
    assert database.get_setting("model") == "opus"
    assert database.get_setting("does-not-exist", "fallback") == "fallback"
    all_values = database.all_settings()
    assert all_values["model"] == "opus"
