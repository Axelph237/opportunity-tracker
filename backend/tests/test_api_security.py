"""Coverage for the newer hardening in main.py: cross-site write protection,
explicit-null rejection on NOT NULL columns, and upload size limits."""

from __future__ import annotations

import database


def _seed_opportunity(conn, **overrides) -> int:
    values = {
        "title": "Quantum Intern", "organization": "IonQ", "type": "internship",
        "url": "https://src.example/jobs/1",
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    conn.execute(f"INSERT INTO opportunities ({columns}) VALUES ({placeholders})", list(values.values()))
    return conn.execute("SELECT id FROM opportunities WHERE url = ?", (values["url"],)).fetchone()["id"]


# ------------------------------------------------------------- cross-site writes

def test_cross_site_post_with_foreign_origin_is_blocked(app_client, db_path):
    resp = app_client.post(
        "/api/sources",
        json={"name": "Evil", "url": "https://evil.example", "type": "job_board"},
        headers={"Origin": "https://evil.example"},
    )
    assert resp.status_code == 403


def test_get_with_foreign_origin_is_not_blocked(app_client, db_path):
    """GET is never state-changing, so it is exempt from the origin check."""
    resp = app_client.get("/api/sources", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 200


def test_post_with_local_origin_is_allowed(app_client, db_path):
    resp = app_client.post(
        "/api/sources",
        json={"name": "Fine", "url": "https://fine.example", "type": "job_board"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert resp.status_code == 201


def test_post_with_no_origin_header_is_allowed(app_client, db_path):
    """curl and the CLI examples in the README send no Origin header at all."""
    resp = app_client.post(
        "/api/sources",
        json={"name": "CLI Add", "url": "https://cli.example", "type": "job_board"},
    )
    assert resp.status_code == 201


# ---------------------------------------------------------------- null rejection

def test_update_opportunity_explicit_null_title_is_422(app_client, db_path):
    with database.get_db() as conn:
        opp_id = _seed_opportunity(conn)
    resp = app_client.patch(f"/api/opportunities/{opp_id}", json={"title": None})
    assert resp.status_code == 422


def test_update_source_explicit_null_name_is_422(app_client, db_path):
    with database.get_db() as conn:
        conn.execute("INSERT INTO sources (name, url, type) VALUES ('S', 'https://s.example', 'job_board')")
        source_id = conn.execute("SELECT id FROM sources WHERE url='https://s.example'").fetchone()["id"]
    resp = app_client.patch(f"/api/sources/{source_id}", json={"name": None})
    assert resp.status_code == 422


def test_update_application_explicit_null_status_is_422(app_client, db_path):
    with database.get_db() as conn:
        opp_id = _seed_opportunity(conn)
    created = app_client.post("/api/applications", json={"opportunity_id": opp_id}).json()
    resp = app_client.patch(f"/api/applications/{created['id']}", json={"status": None})
    assert resp.status_code == 422


# --------------------------------------------------------------- upload size cap

def test_upload_resume_too_large_is_413(app_client):
    big = b"x" * (20_000_001)
    resp = app_client.post(
        "/api/settings/resume",
        files={"file": ("resume.txt", big, "text/plain")},
    )
    assert resp.status_code == 413


def test_upload_walten_context_too_large_is_413(app_client, walten_tmp):
    session = app_client.post("/api/walten/sessions", json={}).json()
    big = b"x" * (20_000_001)
    resp = app_client.post(
        f"/api/walten/sessions/{session['id']}/context",
        files={"file": ("notes.txt", big, "text/plain")},
    )
    assert resp.status_code == 413


def test_upload_walten_context_filename_dotdot_is_sanitized(app_client, walten_tmp):
    """`Path(filename).name` strips directories but leaves '..' itself intact."""
    session = app_client.post("/api/walten/sessions", json={}).json()
    resp = app_client.post(
        f"/api/walten/sessions/{session['id']}/context",
        files={"file": ("..", b"sneaky", "text/plain")},
    )
    assert resp.status_code == 200
    stored_dir = walten_tmp / "data" / "walten-context" / str(session["id"])
    assert (stored_dir / "upload.txt").exists()
    # And nothing escaped the session's own context directory.
    assert not (walten_tmp / "data" / "walten-context.bak").exists()


# --------------------------------------------------------- application race safety

def test_create_application_duplicate_is_409_via_unique_index(app_client, db_path):
    """The 409 now comes from the unique index catching a race, not a pre-check.

    Directly pre-seeding a second application row for the same opportunity
    (bypassing the API, simulating two requests that both passed a
    check-then-insert race) must still be impossible: the schema itself
    enforces one application per opportunity.
    """
    with database.get_db() as conn:
        opp_id = _seed_opportunity(conn)
        conn.execute(
            "INSERT INTO applications (opportunity_id, status) VALUES (?, 'bookmarked')", (opp_id,)
        )

    import sqlite3
    with database.get_db() as conn:
        try:
            conn.execute(
                "INSERT INTO applications (opportunity_id, status) VALUES (?, 'bookmarked')", (opp_id,)
            )
            raised = False
        except sqlite3.IntegrityError:
            raised = True
    assert raised, "the unique index on applications.opportunity_id should reject a second row"


# ------------------------------------------------------------- dedupe migration

def test_dedupe_applications_migration_keeps_oldest_duplicate(tmp_path, monkeypatch):
    """init_db()'s _dedupe_applications must collapse pre-existing duplicates
    (from before the unique index existed) down to the oldest row per
    opportunity, so the new unique index can be created at all."""
    import sqlite3

    path = tmp_path / "dupe.db"
    monkeypatch.setattr(database, "DB_PATH", path)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # Matches every column the full SCHEMA's CREATE INDEX statements touch,
    # so init_db()'s executescript (CREATE TABLE IF NOT EXISTS, which is a
    # no-op here since the table already exists) doesn't fail on a missing
    # column when it gets to the index-creation statements.
    conn.executescript(
        """
        CREATE TABLE opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, organization TEXT NOT NULL,
            type TEXT NOT NULL, url TEXT NOT NULL UNIQUE, source_id INTEGER, relevance_score REAL
        );
        CREATE TABLE applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'bookmarked',
            date_bookmarked TEXT DEFAULT (datetime('now')),
            date_applied TEXT, notes TEXT, last_updated TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX idx_applications_opportunity ON applications(opportunity_id);
        """
    )
    conn.execute("INSERT INTO opportunities (title, organization, type, url) VALUES ('T', 'O', 'job', 'https://x/1')")
    conn.execute("INSERT INTO applications (opportunity_id, status) VALUES (1, 'bookmarked')")
    conn.execute("INSERT INTO applications (opportunity_id, status) VALUES (1, 'applied')")
    conn.commit()
    conn.close()

    database.init_db()

    with database.get_db() as conn:
        rows = conn.execute("SELECT id, status FROM applications WHERE opportunity_id = 1").fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "bookmarked"  # the oldest (lowest id) row survives

    # And the unique index now actually exists and is enforced.
    with database.get_db() as conn:
        try:
            conn.execute("INSERT INTO applications (opportunity_id, status) VALUES (1, 'withdrawn')")
            duplicate_allowed = True
        except sqlite3.IntegrityError:
            duplicate_allowed = False
    assert duplicate_allowed is False
