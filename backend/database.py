"""SQLite connection handling, schema creation, migrations and seed data."""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("DB_PATH", PROJECT_ROOT / "data" / "opportunities.db"))
if not DB_PATH.is_absolute():
    DB_PATH = (PROJECT_ROOT / DB_PATH).resolve()


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    type TEXT NOT NULL CHECK(type IN ('job_board', 'company_careers', 'research_program', 'aggregator', 'university', 'government')),
    scrape_method TEXT NOT NULL DEFAULT 'html' CHECK(scrape_method IN ('html', 'api', 'search_query')),
    search_query TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    last_scraped TEXT,
    last_result_count INTEGER,
    date_added TEXT NOT NULL DEFAULT (datetime('now')),
    added_by TEXT NOT NULL DEFAULT 'user' CHECK(added_by IN ('user', 'claude')),
    pending_approval INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    organization TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('internship', 'job', 'research', 'grad_program', 'fellowship', 'other')),
    location TEXT,
    remote INTEGER DEFAULT 0,
    url TEXT NOT NULL UNIQUE,
    description TEXT,
    deadline TEXT,
    date_found TEXT NOT NULL DEFAULT (datetime('now')),
    source_id INTEGER REFERENCES sources(id),
    relevance_score REAL,
    relevance_summary TEXT,
    skill_matches TEXT,
    experience_level TEXT CHECK(experience_level IN ('entry', 'mid', 'senior', 'student', 'postdoc', 'any')),
    strong_match INTEGER DEFAULT 0,
    tags TEXT,
    notes TEXT,
    is_active INTEGER DEFAULT 1,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'bookmarked' CHECK(status IN (
        'bookmarked', 'planning_to_apply', 'applied', 'assessment',
        'interview', 'offer', 'rejected', 'withdrawn', 'closed'
    )),
    date_bookmarked TEXT DEFAULT (datetime('now')),
    date_applied TEXT,
    deadline_override TEXT,
    cover_letter_notes TEXT,
    contacts TEXT,
    notes TEXT,
    last_updated TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS source_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    type TEXT NOT NULL,
    scrape_method TEXT NOT NULL DEFAULT 'html',
    rationale TEXT,
    confidence REAL,
    date_proposed TEXT DEFAULT (datetime('now')),
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected'))
);

CREATE TABLE IF NOT EXISTS scrape_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    status TEXT NOT NULL CHECK(status IN ('success', 'error')),
    new_count INTEGER DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS walten_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT 'New session',
    claude_session_id TEXT,        -- the CLI session resumed on each turn
    mode TEXT NOT NULL DEFAULT 'assistant' CHECK(mode IN ('assistant', 'engineer')),
    model TEXT NOT NULL DEFAULT 'sonnet',
    context_files TEXT,            -- JSON array of project-relative paths
    context_urls TEXT,             -- JSON array of URLs to consult
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS walten_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES walten_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    phase TEXT NOT NULL DEFAULT 'plan' CHECK(phase IN ('plan', 'apply')),
    content TEXT,
    tool_calls TEXT,               -- JSON array, the audit log for this turn
    cost_usd REAL,
    duration_ms INTEGER,
    tokens_in INTEGER,
    tokens_out INTEGER,
    needs_approval INTEGER NOT NULL DEFAULT 0,
    resolved INTEGER NOT NULL DEFAULT 0,   -- an approval that has been acted on
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS excluded_urls (
    url TEXT PRIMARY KEY,
    reason TEXT NOT NULL DEFAULT 'deleted' CHECK(reason IN ('deleted', 'dead_link')),
    detail TEXT,
    excluded_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS resume_advice (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id INTEGER NOT NULL UNIQUE REFERENCES opportunities(id) ON DELETE CASCADE,
    generated_at TEXT NOT NULL DEFAULT (datetime('now')),
    resume_filename TEXT,          -- which resume the advice was generated against
    fit_summary TEXT,              -- one paragraph on overall fit
    fit_score REAL,                -- 0.0-10.0 how ready the resume is as written
    requirements TEXT,             -- JSON array of {requirement, importance, status, evidence}
    adjustments TEXT,              -- JSON array of {section, current, suggested, rationale, priority}
    keywords TEXT,                 -- JSON array of ATS keywords worth mirroring
    talking_points TEXT            -- JSON array of points to raise in a cover letter / interview
);

CREATE TABLE IF NOT EXISTS role_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT NOT NULL DEFAULT (datetime('now')),
    scope TEXT,                    -- human description of which listings were analysed
    opportunity_count INTEGER NOT NULL DEFAULT 0,
    resume_filename TEXT,
    summary TEXT,                  -- prose overview of the role landscape
    role_groups TEXT,              -- JSON array of {label, count, description, example_titles}
    requirements TEXT,             -- JSON array of {requirement, frequency, status, evidence, gap_note}
    recommended_skills TEXT,       -- JSON array of {skill, why, unlocks, effort, priority}
    edited_at TEXT,                -- set when the user hand-edits the analysis
    strengths TEXT                 -- JSON array of resume strengths worth leading with
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_opportunities_score ON opportunities(relevance_score);
CREATE INDEX IF NOT EXISTS idx_opportunities_source ON opportunities(source_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_opportunity ON applications(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_scrape_logs_source ON scrape_logs(source_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_resume_advice_opportunity ON resume_advice(opportunity_id);
"""


SEED_SOURCES = [
    ("NSF REU Finder", "https://www.nsf.gov/crssprgm/reu/list.jsp", "research_program", "html"),
    ("NASA Internships", "https://intern.nasa.gov", "government", "html"),
    ("DOE SULI Program", "https://science.osti.gov/wdts/suli", "government", "html"),
    ("IBM Quantum Careers", "https://www.ibm.com/quantum/careers", "company_careers", "html"),
    ("Google Quantum AI Jobs", "https://quantumai.google/jobs", "company_careers", "html"),
    ("Microsoft Research Jobs", "https://careers.microsoft.com/v2/global/en/research.html", "company_careers", "html"),
    ("IonQ Careers", "https://ionq.com/careers", "company_careers", "html"),
    ("Quantinuum Careers", "https://www.quantinuum.com/careers", "company_careers", "html"),
    ("PsiQuantum Careers", "https://www.psiquantum.com/careers", "company_careers", "html"),
    ("Atom Computing Careers", "https://atom-computing.com/careers/", "company_careers", "html"),
    ("arXiv Job Listings", "https://arxiv.org/jobs", "aggregator", "html"),
    ("APS Careers", "https://careers.aps.org", "aggregator", "html"),
    ("IEEE Job Site", "https://jobs.ieee.org", "job_board", "html"),
    ("LinkedIn Quantum Jobs", "https://www.linkedin.com/jobs/search/?keywords=quantum+computing", "job_board", "html"),
    ("Indeed Quantum Engineering", "https://www.indeed.com/jobs?q=quantum+engineer", "job_board", "html"),
    ("USAJobs Quantum", "https://www.usajobs.gov/Search/Results?k=quantum", "government", "html"),
    ("Handshake", "https://app.joinhandshake.com/explore", "job_board", "html"),
    ("Sandia National Labs", "https://jobs.sandia.gov", "government", "html"),
    ("Oak Ridge National Lab", "https://jobs.ornl.gov", "government", "html"),
    ("Argonne National Lab", "https://www.anl.gov/careers", "government", "html"),
]


DEFAULT_SETTINGS = {
    "cron_schedule": os.getenv("CRON_SCHEDULE", "0 8,18 * * *"),
    "model": os.getenv("CLAUDE_MODEL", "sonnet"),
    "max_chunks_per_source": "12",
    "request_timeout_seconds": "15",
    "domain_delay_seconds": "2",
    # Fetch every candidate listing URL before storing it, so 404s never reach a table.
    "verify_listing_urls": "1",
    "walten_name": os.getenv("WALTEN_NAME", "Walten"),
    "walten_icon": os.getenv("WALTEN_ICON", "Dog"),
    "claude_bin": "",
    "onboarding_complete": "0",
}


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """Yield a connection, committing on success and always closing."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations for databases created by earlier versions."""
    migrations: dict[str, dict[str, str]] = {
        "opportunities": {
            "relevance_summary": "TEXT",
            "skill_matches": "TEXT",
            "tags": "TEXT",
            "notes": "TEXT",
            "strong_match": "INTEGER DEFAULT 0",
            "is_active": "INTEGER DEFAULT 1",
            "last_seen": "TEXT",
        },
        "sources": {
            "search_query": "TEXT",
            "last_result_count": "INTEGER",
            "pending_approval": "INTEGER NOT NULL DEFAULT 0",
            "notes": "TEXT",
            # How the last scrape attempt ended: 'ok', 'blocked' (the host
            # refused us) or 'error'. Kept on the row so the Sources table can
            # say why a source is not producing listings without joining the log.
            "last_status": "TEXT",
            "last_error": "TEXT",
        },
        "applications": {
            "deadline_override": "TEXT",
            "cover_letter_notes": "TEXT",
            "contacts": "TEXT",
        },
        "role_analyses": {
            "edited_at": "TEXT",
        },
        "walten_messages": {
            # The commit taken when the message was sent, and its tree. The tree
            # is what the undo arrow compares against: two commits can carry the
            # same tree, and restoring one of those is a no-op.
            "snapshot_sha": "TEXT",
            "snapshot_tree": "TEXT",
        },
    }
    for table, columns in migrations.items():
        existing = _column_names(conn, table)
        if not existing:
            continue
        for column, ddl in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _dedupe_applications(conn: sqlite3.Connection) -> None:
    """Collapse duplicate applications so the unique index can be created.

    Before the index existed, two clicks landing together could both pass the
    "is this already tracked?" check and insert. The oldest row is the one the
    user actually created; later clones carry no history worth keeping.
    """
    existing = conn.execute(
        "SELECT name, \"unique\" FROM pragma_index_list('applications') WHERE name = ?",
        ("idx_applications_opportunity",),
    ).fetchone()
    if existing is not None and existing["unique"]:
        return  # already migrated

    duplicates = conn.execute(
        """SELECT opportunity_id, COUNT(*) AS n FROM applications
           GROUP BY opportunity_id HAVING n > 1"""
    ).fetchall()
    if duplicates:
        removed = conn.execute(
            """DELETE FROM applications WHERE id NOT IN (
                   SELECT MIN(id) FROM applications GROUP BY opportunity_id
               )"""
        ).rowcount
        logger.warning(
            "Removed %d duplicate application row(s) across %d listing(s); the oldest of each was kept",
            removed, len(duplicates),
        )
    conn.execute("DROP INDEX IF EXISTS idx_applications_opportunity")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_opportunity ON applications(opportunity_id)"
    )


def seed_sources(conn: sqlite3.Connection) -> int:
    """Insert the starter source list. Existing URLs are left untouched.

    Missing URLs are looked up first rather than relying on INSERT OR IGNORE, so
    re-running startup does not inflate the AUTOINCREMENT counter.
    """
    known = {row["url"] for row in conn.execute("SELECT url FROM sources")}
    missing = [entry for entry in SEED_SOURCES if entry[1] not in known]
    if not missing:
        return 0
    conn.executemany(
        """INSERT INTO sources (name, url, type, scrape_method, active, added_by, pending_approval)
           VALUES (?, ?, ?, ?, 1, 'user', 0)""",
        missing,
    )
    return len(missing)


def seed_settings(conn: sqlite3.Connection) -> None:
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))


def get_setting(key: str, default: str | None = None) -> str | None:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def exclude_url(url: str, reason: str = "deleted", detail: str | None = None) -> None:
    """Remember a URL that must not come back on the next scrape.

    'deleted' is permanent (the user threw the listing away); 'dead_link' expires
    after RECHECK_DEAD_AFTER_DAYS so a site that was briefly broken gets another try.
    """
    with get_db() as conn:
        conn.execute(
            """INSERT INTO excluded_urls (url, reason, detail, excluded_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(url) DO UPDATE SET
                   reason = excluded.reason,
                   detail = excluded.detail,
                   excluded_at = excluded.excluded_at""",
            (url, reason, detail),
        )


RECHECK_DEAD_AFTER_DAYS = 14


def excluded_urls(conn: sqlite3.Connection | None = None) -> set[str]:
    """URLs the scraper must skip right now."""
    query = f"""SELECT url FROM excluded_urls
                WHERE reason = 'deleted'
                   OR excluded_at > datetime('now', '-{RECHECK_DEAD_AFTER_DAYS} days')"""
    if conn is not None:
        return {row["url"] for row in conn.execute(query)}
    with get_db() as own:
        return {row["url"] for row in own.execute(query)}


def set_setting(key: str, value: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def all_settings() -> dict[str, str]:
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    return {row["key"]: row["value"] for row in rows}


def init_db() -> None:
    """Create tables, run migrations and seed first-run data."""
    with get_db() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        _dedupe_applications(conn)
        seed_sources(conn)
        seed_settings(conn)


if __name__ == "__main__":
    init_db()
    with get_db() as conn:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
            for table in (
                "sources", "opportunities", "applications", "source_proposals",
                "scrape_logs", "resume_advice", "role_analyses", "settings",
            )
        }
    print(f"Database ready at {DB_PATH}")
    for table, count in counts.items():
        print(f"  {table:18} {count}")
