"""FastAPI application: every route for opportunities, applications, sources,
scraping and settings."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import advisor
import scheduler as scheduler_module
import walten as walten_module
import source_discovery
from classifier import STRONG_MATCH_THRESHOLD
from claude_cli import ClaudeCallError, ClaudeUnavailable, claude_available, claude_bin, claude_version
from database import DB_PATH, PROJECT_ROOT, all_settings, exclude_url, get_db, get_setting, init_db, set_setting
from models import (
    APPLICATION_STATUSES,
    ResumeAdvice,
    RoleAnalysis,
    RoleAnalysisRequest,
    RoleAnalysisUpdate,
    Application,
    ApplicationCreate,
    ApplicationUpdate,
    DiscoveryRequest,
    Opportunity,
    OpportunityDetail,
    OpportunityUpdate,
    ResumeStatus,
    ScrapeLog,
    ScrapeStatus,
    SettingsUpdate,
    Source,
    SourceCreate,
    SourceProposal,
    SourceUpdate,
    WaltenMessage,
    WaltenPrompt,
    WaltenSession,
    WaltenSessionCreate,
    WaltenSessionDetail,
    WaltenSessionUpdate,
    WaltenUndoPreview,
    WaltenUndoResult,
)
from resume_loader import load_resume, resume_status, save_resume
from scheduler import runner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

SORT_COLUMNS = {
    "date_found": "o.date_found",
    "relevance_score": "o.relevance_score",
    "deadline": "o.deadline",
    "title": "o.title COLLATE NOCASE",
    "organization": "o.organization COLLATE NOCASE",
    "type": "o.type",
    "location": "o.location COLLATE NOCASE",
    "experience_level": "o.experience_level",
    "source": "s.name COLLATE NOCASE",
    "application_status": "a.status",
    "advice_generated_at": "adv.generated_at",
}
SOURCE_SORT_COLUMNS = {
    "name": "name COLLATE NOCASE",
    "type": "type",
    "active": "active",
    "last_scraped": "last_scraped",
    "last_result_count": "last_result_count",
    "date_added": "date_added",
    "added_by": "added_by",
    "url": "url COLLATE NOCASE",
}
APPLICATION_SORT_COLUMNS = {
    "status": "a.status",
    "title": "o.title COLLATE NOCASE",
    "organization": "o.organization COLLATE NOCASE",
    "relevance_score": "o.relevance_score",
    "deadline": "COALESCE(a.deadline_override, o.deadline)",
    "date_bookmarked": "a.date_bookmarked",
    "date_applied": "a.date_applied",
    "last_updated": "a.last_updated",
}
LOG_SORT_COLUMNS = {
    "timestamp": "l.timestamp",
    "status": "l.status",
    "new_count": "l.new_count",
    "source": "s.name COLLATE NOCASE",
}
MUTABLE_SETTINGS = {
    "cron_schedule",
    "model",
    "max_chunks_per_source",
    "request_timeout_seconds",
    "domain_delay_seconds",
    "verify_listing_urls",
    "walten_name",
    "walten_icon",
    "claude_bin",
    "onboarding_complete",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    load_resume()
    scheduler_module.start()
    logger.info("Database: %s | claude CLI available: %s", DB_PATH, claude_available())
    try:
        yield
    finally:
        scheduler_module.shutdown()


app = FastAPI(title="Opportunity Tracker", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", ""}

# Uploads are read into memory before anything is checked, so the ceiling has to
# come before the read is trusted. A resume or a context note is kilobytes.
MAX_UPLOAD_BYTES = 20_000_000


@app.middleware("http")
async def block_cross_site_writes(request: Request, call_next):
    """Refuse state-changing requests that come from another site.

    There is no authentication here — the app is meant to be reached only from
    the machine it runs on. That makes it reachable by any page the owner has
    open: a POST with no body and no custom headers is a CORS "simple request",
    so a browser sends it cross-origin with no preflight and CORS never gets a
    say. `POST /api/walten/sessions/1/approve` takes no body and session ids
    count up from 1, so any site could have promoted a pending plan into the
    write-enabled phase — the exact gate the approval flow exists to hold.

    Requests with no Origin header (curl, the scripts, the CLI examples in the
    README) are left alone; browsers always send one on a cross-site write.
    """
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin:
            host = urlparse(origin).hostname or ""
            if host not in LOCAL_HOSTS:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Cross-site requests are not accepted by this app."},
                )
    return await call_next(request)


# ------------------------------------------------------------------------- helpers

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json_list(value: Any) -> list:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return [part.strip() for part in str(value).split(",") if part.strip()]
    return parsed if isinstance(parsed, list) else []


def opportunity_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["skill_matches"] = _json_list(data.get("skill_matches"))
    data["tags"] = _json_list(data.get("tags"))
    data["remote"] = bool(data.get("remote"))
    data["strong_match"] = bool(data.get("strong_match"))
    data["is_active"] = bool(data.get("is_active", 1))
    return data


def application_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["contacts"] = _json_list(data.get("contacts"))
    return data


def source_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["active"] = bool(data.get("active"))
    data["pending_approval"] = bool(data.get("pending_approval"))
    return data


def _order_clause(column: str, order: str) -> str:
    """Sort with NULLs always last, whichever direction the user picked."""
    direction = "ASC" if str(order).lower() == "asc" else "DESC"
    return f"CASE WHEN {column} IS NULL OR {column} = '' THEN 1 ELSE 0 END ASC, {column} {direction}"


def _fetch_opportunity(conn: sqlite3.Connection, opportunity_id: int) -> sqlite3.Row:
    row = conn.execute(
        """SELECT o.*, s.name AS source_name, a.id AS application_id, a.status AS application_status,
                  adv.generated_at AS advice_generated_at
           FROM opportunities o
           LEFT JOIN sources s ON s.id = o.source_id
           LEFT JOIN applications a ON a.opportunity_id = o.id
           LEFT JOIN resume_advice adv ON adv.opportunity_id = o.id
           WHERE o.id = ?""",
        (opportunity_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Opportunity {opportunity_id} not found")
    return row


def _apply_updates(conn: sqlite3.Connection, table: str, row_id: int, values: dict[str, Any]) -> None:
    if not values:
        return
    assignments = ", ".join(f"{column} = ?" for column in values)
    conn.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", [*values.values(), row_id])


def _reject_nulls(values: dict[str, Any], required: tuple[str, ...]) -> None:
    """Refuse an explicit null for a column the schema declares NOT NULL.

    Every update model marks its fields Optional so `exclude_unset` can tell
    "not sent" from "sent", which also makes `{"status": null}` a valid request
    body. Without this it reaches SQLite and comes back as a bare 500.
    """
    for field in required:
        if field in values and values[field] is None:
            raise HTTPException(status_code=422, detail=f"`{field}` cannot be empty")


def _integrity_error(exc: sqlite3.IntegrityError, *, unique_detail: str) -> HTTPException:
    """Turn a constraint violation into the error it actually is.

    Blaming every IntegrityError on a duplicate URL told the user their URL was
    taken when what really happened was a missing required field.
    """
    message = str(exc)
    if "UNIQUE" in message:
        return HTTPException(status_code=409, detail=unique_detail)
    if "NOT NULL" in message:
        column = message.rsplit(".", 1)[-1] if "." in message else "a required field"
        return HTTPException(status_code=422, detail=f"`{column}` cannot be empty")
    return HTTPException(status_code=422, detail=f"That change is not allowed: {message}")


# -------------------------------------------------------------------------- health

@app.get("/api/health")
def health() -> dict[str, Any]:
    with get_db() as conn:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
            for table in ("sources", "opportunities", "applications", "source_proposals")
        }
    return {
        "status": "ok",
        "database": str(DB_PATH),
        "claude_cli": claude_available(),
        "resume": resume_status(),
        "counts": counts,
    }


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(
            """SELECT
                   (SELECT COUNT(*) FROM opportunities WHERE is_active = 1) AS opportunities,
                   (SELECT COUNT(*) FROM opportunities WHERE is_active = 1 AND strong_match = 1) AS strong_matches,
                   (SELECT COUNT(*) FROM applications) AS applications,
                   (SELECT COUNT(*) FROM sources WHERE active = 1 AND pending_approval = 0) AS active_sources,
                   (SELECT COUNT(*) FROM source_proposals WHERE status = 'pending') AS pending_proposals"""
        ).fetchone()
    # The sidebar polls this, so the agent's configurable name rides along with it.
    return {
        **dict(row),
        "walten_name": walten_module.walten_name(),
        "walten_icon": walten_module.walten_icon(),
        # Drives the first-run setup gate in the UI.
        "onboarding_complete": (get_setting("onboarding_complete") or "0") != "0",
    }


# ------------------------------------------------------------------- opportunities

@app.get("/api/opportunities", response_model=list[Opportunity])
def list_opportunities(
    type: Optional[list[str]] = Query(None),
    strong_match: Optional[bool] = None,
    experience_level: Optional[list[str]] = Query(None),
    source_id: Optional[int] = None,
    search: Optional[str] = None,
    status: Optional[str] = None,
    remote: Optional[bool] = None,
    has_advice: Optional[bool] = None,
    min_score: Optional[float] = Query(None, ge=0, le=10),
    max_score: Optional[float] = Query(None, ge=0, le=10),
    deadline_within_days: Optional[int] = Query(None, ge=0, le=365),
    sort: str = "relevance_score",
    order: str = "desc",
    include_inactive: bool = False,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[Opportunity]:
    clauses: list[str] = []
    params: list[Any] = []

    if not include_inactive:
        clauses.append("o.is_active = 1")
    if type:
        clauses.append(f"o.type IN ({','.join('?' * len(type))})")
        params.extend(type)
    if strong_match is not None:
        clauses.append("o.strong_match = ?")
        params.append(int(strong_match))
    if experience_level:
        clauses.append(f"o.experience_level IN ({','.join('?' * len(experience_level))})")
        params.extend(experience_level)
    if source_id is not None:
        clauses.append("o.source_id = ?")
        params.append(source_id)
    if search:
        needle = f"%{search.strip()}%"
        clauses.append(
            "(o.title LIKE ? OR o.organization LIKE ? OR o.tags LIKE ? OR o.skill_matches LIKE ?"
            " OR o.description LIKE ? OR o.location LIKE ?)"
        )
        params.extend([needle] * 6)
    if status:
        if status == "none":
            clauses.append("a.id IS NULL")
        else:
            clauses.append("a.status = ?")
            params.append(status)
    if remote is not None:
        clauses.append("o.remote = ?")
        params.append(int(remote))
    if has_advice is not None:
        clauses.append("adv.id IS NOT NULL" if has_advice else "adv.id IS NULL")
    if min_score is not None:
        clauses.append("o.relevance_score >= ?")
        params.append(min_score)
    if max_score is not None:
        clauses.append("o.relevance_score <= ?")
        params.append(max_score)
    if deadline_within_days is not None:
        clauses.append("o.deadline IS NOT NULL AND date(o.deadline) <= date('now', ?)")
        params.append(f"+{int(deadline_within_days)} days")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sort_column = SORT_COLUMNS.get(sort, SORT_COLUMNS["relevance_score"])

    query = f"""SELECT o.*, s.name AS source_name, a.id AS application_id, a.status AS application_status,
                       adv.generated_at AS advice_generated_at
                FROM opportunities o
                LEFT JOIN sources s ON s.id = o.source_id
                LEFT JOIN applications a ON a.opportunity_id = o.id
                LEFT JOIN resume_advice adv ON adv.opportunity_id = o.id
                {where}
                ORDER BY {_order_clause(sort_column, order)}, o.id DESC
                LIMIT ? OFFSET ?"""
    params.extend([limit, offset])

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    return [Opportunity(**opportunity_dict(row)) for row in rows]


@app.get("/api/opportunities/{opportunity_id}", response_model=OpportunityDetail)
def get_opportunity(opportunity_id: int) -> OpportunityDetail:
    with get_db() as conn:
        row = _fetch_opportunity(conn, opportunity_id)
        application_row = conn.execute(
            "SELECT * FROM applications WHERE opportunity_id = ?", (opportunity_id,)
        ).fetchone()

    detail = OpportunityDetail(**opportunity_dict(row))
    if application_row:
        detail.application = Application(**application_dict(application_row))
    return detail


# Plain columns the user may edit by hand, and the two stored as JSON arrays.
OPPORTUNITY_TEXT_FIELDS = (
    "title", "organization", "type", "location", "url",
    "description", "deadline", "experience_level", "relevance_summary", "notes",
)
OPPORTUNITY_JSON_FIELDS = ("tags", "skill_matches")


@app.patch("/api/opportunities/{opportunity_id}", response_model=OpportunityDetail)
def update_opportunity(opportunity_id: int, payload: OpportunityUpdate) -> OpportunityDetail:
    """Edit a listing by hand. Only the fields present in the body are changed.

    A rescrape never rewrites a stored listing — it only refreshes `last_seen` —
    so manual corrections survive the next run.
    """
    values: dict[str, Any] = {}
    data = payload.model_dump(exclude_unset=True)

    for field in OPPORTUNITY_TEXT_FIELDS:
        if field in data:
            value = data[field]
            # Blank out an optional field rather than storing an empty string.
            values[field] = value if value not in ("", None) else None
    for field in OPPORTUNITY_JSON_FIELDS:
        if field in data:
            values[field] = json.dumps([item for item in (data[field] or []) if str(item).strip()])
    for field in ("remote", "is_active"):
        if field in data and data[field] is not None:
            values[field] = int(bool(data[field]))
    if "relevance_score" in data and data["relevance_score"] is not None:
        score = max(0.0, min(10.0, float(data["relevance_score"])))
        values["relevance_score"] = score
        values["strong_match"] = int(score >= STRONG_MATCH_THRESHOLD)

    _reject_nulls(values, ("title", "organization", "url", "type"))

    with get_db() as conn:
        _fetch_opportunity(conn, opportunity_id)
        try:
            _apply_updates(conn, "opportunities", opportunity_id, values)
        except sqlite3.IntegrityError as exc:
            raise _integrity_error(exc, unique_detail="Another listing already uses that URL") from exc
    return get_opportunity(opportunity_id)


@app.delete("/api/opportunities/{opportunity_id}", status_code=204)
def delete_opportunity(opportunity_id: int, forget: bool = True) -> None:
    """Remove a listing, and by default remember its URL so a scrape cannot re-add it.

    Any tracked application and saved resume advice go with it (ON DELETE CASCADE).
    Pass `forget=false` to allow the scraper to pick the listing up again later.
    """
    with get_db() as conn:
        row = _fetch_opportunity(conn, opportunity_id)
        url = row["url"]
        conn.execute("DELETE FROM opportunities WHERE id = ?", (opportunity_id,))
    if forget:
        exclude_url(url, "deleted", "removed from the opportunities table")


# ------------------------------------------------------- resume advice per listing

@app.get("/api/opportunities/{opportunity_id}/resume-advice", response_model=ResumeAdvice)
def get_resume_advice(opportunity_id: int) -> ResumeAdvice:
    """Cached resume advice for one listing. 404 when none has been generated yet."""
    with get_db() as conn:
        _fetch_opportunity(conn, opportunity_id)
    advice = advisor.get_resume_advice(opportunity_id)
    if advice is None:
        raise HTTPException(
            status_code=404,
            detail="No resume advice generated for this opportunity yet. POST to this path to create it.",
        )
    return ResumeAdvice(**advice)


@app.post("/api/opportunities/{opportunity_id}/resume-advice", response_model=ResumeAdvice)
def create_resume_advice(opportunity_id: int, refresh: bool = False) -> ResumeAdvice:
    """Ask Claude how to adjust the resume for this listing.

    Returns the cached result unless `refresh=true`, so re-opening a listing is free.
    """
    with get_db() as conn:
        _fetch_opportunity(conn, opportunity_id)

    if not refresh:
        cached = advisor.get_resume_advice(opportunity_id)
        if cached and not cached["stale"]:
            return ResumeAdvice(**cached)

    try:
        return ResumeAdvice(**advisor.generate_resume_advice(opportunity_id))
    except advisor.AdvisorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ClaudeUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.delete("/api/opportunities/{opportunity_id}/resume-advice", status_code=204)
def delete_resume_advice(opportunity_id: int) -> None:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM resume_advice WHERE opportunity_id = ?", (opportunity_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="No resume advice to delete")


# ----------------------------------------------------- aggregate role landscape

@app.get("/api/insights/roles", response_model=Optional[RoleAnalysis])
def get_role_analysis() -> Optional[RoleAnalysis]:
    """The most recent aggregate analysis, or null if none has been run."""
    analysis = advisor.get_latest_role_analysis()
    return RoleAnalysis(**analysis) if analysis else None


@app.post("/api/insights/roles", response_model=RoleAnalysis)
def create_role_analysis(payload: RoleAnalysisRequest | None = None) -> RoleAnalysis:
    """Summarise the tracked roles: what they require, what the resume covers, what to learn.

    Accepts the same filters as the opportunities list so a subset can be analysed.
    """
    request = payload or RoleAnalysisRequest()
    clauses = ["o.is_active = 1"]
    params: list[Any] = []
    described: list[str] = []

    if request.type:
        clauses.append(f"o.type IN ({','.join('?' * len(request.type))})")
        params.extend(request.type)
        described.append(f"type in {', '.join(request.type)}")
    if request.strong_match is not None:
        clauses.append("o.strong_match = ?")
        params.append(int(request.strong_match))
        described.append("strong matches only" if request.strong_match else "excluding strong matches")
    if request.experience_level:
        clauses.append(f"o.experience_level IN ({','.join('?' * len(request.experience_level))})")
        params.extend(request.experience_level)
        described.append(f"level in {', '.join(request.experience_level)}")
    if request.source_id is not None:
        clauses.append("o.source_id = ?")
        params.append(request.source_id)
        described.append(f"source {request.source_id}")
    if request.search:
        needle = f"%{request.search.strip()}%"
        clauses.append("(o.title LIKE ? OR o.organization LIKE ? OR o.tags LIKE ? OR o.description LIKE ?)")
        params.extend([needle] * 4)
        described.append(f"matching '{request.search.strip()}'")
    if request.status:
        if request.status == "none":
            clauses.append("a.id IS NULL")
            described.append("not yet tracked")
        else:
            clauses.append("a.status = ?")
            params.append(request.status)
            described.append(f"application status {request.status}")

    params.append(request.limit)
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT o.* FROM opportunities o
                LEFT JOIN applications a ON a.opportunity_id = o.id
                WHERE {' AND '.join(clauses)}
                ORDER BY o.relevance_score DESC NULLS LAST, o.id DESC
                LIMIT ?""",
            params,
        ).fetchall()

    scope = "All active opportunities" if not described else "Active opportunities: " + "; ".join(described)
    scope = f"{scope} (top {len(rows)} by relevance)"

    try:
        return RoleAnalysis(**advisor.generate_role_analysis(rows, scope=scope))
    except advisor.AdvisorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ClaudeUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.patch("/api/insights/roles/{analysis_id}", response_model=RoleAnalysis)
def update_role_analysis(analysis_id: int, payload: RoleAnalysisUpdate) -> RoleAnalysis:
    """Correct a stored analysis by hand — Claude's read of a requirement is a
    starting point, not the last word. Edited analyses are stamped `edited_at`."""
    values = payload.model_dump(exclude_unset=True)
    updated = advisor.update_role_analysis(analysis_id, values)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Role analysis {analysis_id} not found")
    return RoleAnalysis(**updated)


@app.get("/api/insights/roles/history", response_model=list[RoleAnalysis])
def role_analysis_history(limit: int = Query(10, ge=1, le=50)) -> list[RoleAnalysis]:
    with get_db() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM role_analyses ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()]
    history = []
    for analysis_id in ids:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM role_analyses WHERE id = ?", (analysis_id,)).fetchone()
        history.append(RoleAnalysis(**{
            "id": row["id"],
            "generated_at": row["generated_at"],
            "edited_at": row["edited_at"],
            "scope": row["scope"],
            "opportunity_count": row["opportunity_count"],
            "resume_filename": row["resume_filename"],
            "summary": row["summary"],
            "role_groups": _json_list(row["role_groups"]),
            "requirements": _json_list(row["requirements"]),
            "recommended_skills": _json_list(row["recommended_skills"]),
            "strengths": _json_list(row["strengths"]),
        }))
    return history


# -------------------------------------------------------------------- applications

@app.get("/api/applications", response_model=list[Application])
def list_applications(
    status: Optional[list[str]] = Query(None),
    type: Optional[list[str]] = Query(None),
    strong_match: Optional[bool] = None,
    source_id: Optional[int] = None,
    search: Optional[str] = None,
    deadline_within_days: Optional[int] = Query(None, ge=0, le=365),
    sort: str = "last_updated",
    order: str = "desc",
) -> list[Application]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append(f"a.status IN ({','.join('?' * len(status))})")
        params.extend(status)
    if type:
        clauses.append(f"o.type IN ({','.join('?' * len(type))})")
        params.extend(type)
    if strong_match is not None:
        clauses.append("o.strong_match = ?")
        params.append(int(strong_match))
    if source_id is not None:
        clauses.append("o.source_id = ?")
        params.append(source_id)
    if search:
        needle = f"%{search.strip()}%"
        clauses.append(
            "(o.title LIKE ? OR o.organization LIKE ? OR o.tags LIKE ? OR a.notes LIKE ?"
            " OR a.cover_letter_notes LIKE ? OR a.contacts LIKE ?)"
        )
        params.extend([needle] * 6)
    if deadline_within_days is not None:
        clauses.append(
            "COALESCE(a.deadline_override, o.deadline) IS NOT NULL"
            " AND date(COALESCE(a.deadline_override, o.deadline)) <= date('now', ?)"
        )
        params.append(f"+{int(deadline_within_days)} days")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sort_column = APPLICATION_SORT_COLUMNS.get(sort, APPLICATION_SORT_COLUMNS["last_updated"])
    query = f"""SELECT a.* FROM applications a
                JOIN opportunities o ON o.id = a.opportunity_id
                {where}
                ORDER BY {_order_clause(sort_column, order)}, a.id DESC"""

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        applications: list[Application] = []
        for row in rows:
            application = Application(**application_dict(row))
            opportunity_row = _fetch_opportunity(conn, row["opportunity_id"])
            application.opportunity = Opportunity(**opportunity_dict(opportunity_row))
            applications.append(application)
    return applications


@app.post("/api/applications", response_model=Application, status_code=201)
def create_application(payload: ApplicationCreate) -> Application:
    with get_db() as conn:
        _fetch_opportunity(conn, payload.opportunity_id)
        # The unique index on opportunity_id is what actually enforces "one
        # application per listing". Checking first and then inserting is not
        # atomic: two clicks landing together both saw no row and both inserted,
        # and because the opportunities list LEFT JOINs applications, the
        # listing then appeared once per duplicate.
        try:
            cur = conn.execute(
                """INSERT INTO applications (opportunity_id, status, date_bookmarked, notes, last_updated)
                   VALUES (?, ?, ?, ?, ?)""",
                (payload.opportunity_id, payload.status, _now(), payload.notes, _now()),
            )
        except sqlite3.IntegrityError as exc:
            if "UNIQUE" not in str(exc):
                raise _integrity_error(exc, unique_detail="That application already exists") from exc
            existing = conn.execute(
                "SELECT id FROM applications WHERE opportunity_id = ?", (payload.opportunity_id,)
            ).fetchone()
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Opportunity {payload.opportunity_id} is already tracked as "
                    f"application {existing['id'] if existing else 'another row'}"
                ),
            ) from exc
        row = conn.execute("SELECT * FROM applications WHERE id = ?", (cur.lastrowid,)).fetchone()
        application = Application(**application_dict(row))
        application.opportunity = Opportunity(**opportunity_dict(_fetch_opportunity(conn, payload.opportunity_id)))
    return application


@app.patch("/api/applications/{application_id}", response_model=Application)
def update_application(application_id: int, payload: ApplicationUpdate) -> Application:
    data = payload.model_dump(exclude_unset=True)
    values: dict[str, Any] = {}
    for field in ("status", "date_applied", "deadline_override", "cover_letter_notes", "notes"):
        if field in data:
            values[field] = data[field]
    if "contacts" in data:
        values["contacts"] = json.dumps(
            [contact.model_dump(exclude_none=True) if hasattr(contact, "model_dump") else contact
             for contact in (data["contacts"] or [])]
        )
    # Stamp the application date the first time the status flips to 'applied'.
    if values.get("status") == "applied" and "date_applied" not in values:
        values["date_applied"] = _now()
    values["last_updated"] = _now()
    _reject_nulls(values, ("status",))

    with get_db() as conn:
        row = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Application {application_id} not found")
        try:
            _apply_updates(conn, "applications", application_id, values)
        except sqlite3.IntegrityError as exc:
            raise _integrity_error(exc, unique_detail="That application already exists") from exc
        updated = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
        application = Application(**application_dict(updated))
        application.opportunity = Opportunity(**opportunity_dict(_fetch_opportunity(conn, updated["opportunity_id"])))
    return application


@app.delete("/api/applications/{application_id}", status_code=204)
def delete_application(application_id: int) -> None:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM applications WHERE id = ?", (application_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Application {application_id} not found")


@app.get("/api/applications/statuses")
def application_statuses() -> list[str]:
    return APPLICATION_STATUSES


# -------------------------------------------------------------------------- sources

@app.get("/api/sources", response_model=list[Source])
def list_sources(
    active: Optional[bool] = None,
    include_pending: bool = False,
    type: Optional[list[str]] = Query(None),
    scrape_method: Optional[list[str]] = Query(None),
    added_by: Optional[str] = None,
    search: Optional[str] = None,
    never_scraped: Optional[bool] = None,
    sort: str = "name",
    order: str = "asc",
) -> list[Source]:
    clauses: list[str] = []
    params: list[Any] = []
    if not include_pending:
        clauses.append("pending_approval = 0")
    if active is not None:
        clauses.append("active = ?")
        params.append(int(active))
    if type:
        clauses.append(f"type IN ({','.join('?' * len(type))})")
        params.extend(type)
    if scrape_method:
        clauses.append(f"scrape_method IN ({','.join('?' * len(scrape_method))})")
        params.extend(scrape_method)
    if added_by:
        clauses.append("added_by = ?")
        params.append(added_by)
    if search:
        needle = f"%{search.strip()}%"
        clauses.append("(name LIKE ? OR url LIKE ? OR notes LIKE ? OR search_query LIKE ?)")
        params.extend([needle] * 4)
    if never_scraped is not None:
        clauses.append("last_scraped IS NULL" if never_scraped else "last_scraped IS NOT NULL")

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sort_column = SOURCE_SORT_COLUMNS.get(sort, SOURCE_SORT_COLUMNS["name"])

    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM sources {where} ORDER BY {_order_clause(sort_column, order)}, id ASC", params
        ).fetchall()
    return [Source(**source_dict(row)) for row in rows]


@app.post("/api/sources", response_model=Source, status_code=201)
def create_source(payload: SourceCreate) -> Source:
    with get_db() as conn:
        try:
            cur = conn.execute(
                """INSERT INTO sources (name, url, type, scrape_method, search_query, active, added_by, pending_approval, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    payload.name,
                    payload.url,
                    payload.type,
                    payload.scrape_method,
                    payload.search_query,
                    int(payload.active),
                    payload.added_by,
                    int(payload.pending_approval),
                    payload.notes,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail=f"A source with URL {payload.url} already exists") from exc
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (cur.lastrowid,)).fetchone()
    return Source(**source_dict(row))


@app.patch("/api/sources/{source_id}", response_model=Source)
def update_source(source_id: int, payload: SourceUpdate) -> Source:
    data = payload.model_dump(exclude_unset=True)
    values: dict[str, Any] = {}
    for field in ("name", "url", "type", "scrape_method", "search_query", "notes"):
        if field in data:
            values[field] = data[field]
    for field in ("active", "pending_approval"):
        if field in data:
            values[field] = int(bool(data[field]))

    _reject_nulls(values, ("name", "url", "type", "scrape_method"))

    with get_db() as conn:
        current = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if current is None:
            raise HTTPException(status_code=404, detail=f"Source {source_id} not found")

        # Pointing the source somewhere else makes the last result meaningless —
        # and a "blocked" flag left behind would keep the Scrape button disabled
        # for a URL that was never tried, which is the fix for being blocked in
        # the first place.
        fetched_differently = any(
            field in values and values[field] != current[field]
            for field in ("url", "scrape_method", "search_query")
        )
        if fetched_differently and current["last_status"]:
            values["last_status"] = None
            values["last_error"] = None

        try:
            _apply_updates(conn, "sources", source_id, values)
        except sqlite3.IntegrityError as exc:
            raise _integrity_error(exc, unique_detail="Another source already uses that URL") from exc
        row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    return Source(**source_dict(row))


@app.delete("/api/sources/{source_id}", status_code=204)
def delete_source(source_id: int) -> None:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Source {source_id} not found")


@app.post("/api/sources/discover", response_model=list[SourceProposal])
def discover_sources_endpoint(payload: DiscoveryRequest | None = None) -> list[SourceProposal]:
    request = payload or DiscoveryRequest()
    try:
        saved = source_discovery.run_discovery(count=request.count, focus=request.focus)
    except ClaudeUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ClaudeCallError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"Source discovery failed: {exc}") from exc
    return [SourceProposal(**proposal) for proposal in saved]


@app.get("/api/sources/proposals", response_model=list[SourceProposal])
def list_proposals(status: str = "pending") -> list[SourceProposal]:
    query = "SELECT * FROM source_proposals"
    params: list[Any] = []
    if status != "all":
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY confidence DESC, id DESC"
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    return [SourceProposal(**dict(row)) for row in rows]


@app.post("/api/sources/proposals/{proposal_id}/approve", response_model=Source)
def approve_proposal(proposal_id: int) -> Source:
    with get_db() as conn:
        proposal = conn.execute("SELECT * FROM source_proposals WHERE id = ?", (proposal_id,)).fetchone()
        if proposal is None:
            raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")
        if proposal["status"] == "approved":
            raise HTTPException(status_code=409, detail="Proposal has already been approved")

        try:
            conn.execute(
                """INSERT INTO sources (name, url, type, scrape_method, active, added_by, pending_approval, notes)
                   VALUES (?, ?, ?, ?, 1, 'claude', 0, ?)""",
                (
                    proposal["name"],
                    proposal["url"],
                    proposal["type"],
                    proposal["scrape_method"],
                    proposal["rationale"],
                ),
            )
        except sqlite3.IntegrityError as exc:
            conn.execute("UPDATE source_proposals SET status = 'approved' WHERE id = ?", (proposal_id,))
            raise HTTPException(status_code=409, detail=f"Source {proposal['url']} already exists") from exc

        conn.execute("UPDATE source_proposals SET status = 'approved' WHERE id = ?", (proposal_id,))
        row = conn.execute("SELECT * FROM sources WHERE url = ?", (proposal["url"],)).fetchone()
    return Source(**source_dict(row))


@app.post("/api/sources/proposals/{proposal_id}/reject", response_model=SourceProposal)
def reject_proposal(proposal_id: int) -> SourceProposal:
    with get_db() as conn:
        if conn.execute("SELECT 1 FROM source_proposals WHERE id = ?", (proposal_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")
        conn.execute("UPDATE source_proposals SET status = 'rejected' WHERE id = ?", (proposal_id,))
        row = conn.execute("SELECT * FROM source_proposals WHERE id = ?", (proposal_id,)).fetchone()
    return SourceProposal(**dict(row))


# ------------------------------------------------------------------------- scraping

@app.post("/api/scrape/run-now")
async def run_scrape_now(background_tasks: BackgroundTasks) -> dict[str, Any]:
    if runner.running:
        raise HTTPException(status_code=409, detail="A scrape is already running")
    background_tasks.add_task(runner.run, None)
    return {"started": True, "message": "Scrape started in the background"}


@app.post("/api/scrape/source/{source_id}")
async def run_scrape_source(source_id: int, background_tasks: BackgroundTasks) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute("SELECT id, name FROM sources WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    if runner.running:
        raise HTTPException(status_code=409, detail="A scrape is already running")
    background_tasks.add_task(runner.run, [source_id])
    return {"started": True, "source_id": source_id, "message": f"Scraping {row['name']} in the background"}


@app.get("/api/scrape/status", response_model=ScrapeStatus)
def scrape_status() -> ScrapeStatus:
    return ScrapeStatus(**scheduler_module.status())


@app.get("/api/scrape/log-tail")
def scrape_log_tail(limit: int = Query(100, ge=1, le=400)) -> dict[str, Any]:
    return {"running": runner.running, "lines": runner.log_tail(limit)}


@app.get("/api/scrape/logs", response_model=list[ScrapeLog])
def scrape_logs(
    source_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "timestamp",
    order: str = "desc",
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[ScrapeLog]:
    clauses: list[str] = []
    params: list[Any] = []
    if source_id is not None:
        clauses.append("l.source_id = ?")
        params.append(source_id)
    if status:
        clauses.append("l.status = ?")
        params.append(status)
    if search:
        needle = f"%{search.strip()}%"
        clauses.append("(s.name LIKE ? OR l.error_message LIKE ?)")
        params.extend([needle] * 2)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sort_column = LOG_SORT_COLUMNS.get(sort, LOG_SORT_COLUMNS["timestamp"])
    params.extend([limit, offset])

    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT l.*, s.name AS source_name FROM scrape_logs l
                LEFT JOIN sources s ON s.id = l.source_id
                {where}
                ORDER BY {_order_clause(sort_column, order)}, l.id DESC
                LIMIT ? OFFSET ?""",
            params,
        ).fetchall()
    return [ScrapeLog(**dict(row)) for row in rows]



# ------------------------------------------------------------------------ walten

def _walten_session_row(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM walten_sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return row


def _walten_session_dict(row: sqlite3.Row, message_count: int = 0) -> dict[str, Any]:
    data = dict(row)
    data["context_files"] = _json_list(data.get("context_files"))
    data["context_urls"] = _json_list(data.get("context_urls"))
    data["message_count"] = message_count
    data.pop("claude_session_id", None)
    return data


def _walten_message_dict(row: sqlite3.Row, git_state: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    data = dict(row)
    data["tool_calls"] = _json_list(data.get("tool_calls"))
    data["needs_approval"] = bool(data.get("needs_approval"))
    data["resolved"] = bool(data.get("resolved"))
    # Undo is offered only when it would actually do something. `git_state` is
    # read once per request and answers that for every message without a diff
    # per row: a checkpoint is stale if the tree moved on, or if anything is
    # uncommitted (in which case every checkpoint differs from disk).
    tree = data.pop("snapshot_tree", None)
    data["can_undo"] = bool(
        git_state
        and git_state.get("ok")
        and tree
        and (git_state.get("dirty") or git_state.get("tree") != tree)
    )
    return data


@app.get("/api/walten", response_model=dict)
def walten_overview() -> dict[str, Any]:
    """Name, availability and the session list, for the sidebar and the page."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT s.*, (SELECT COUNT(*) FROM walten_messages m WHERE m.session_id = s.id) AS n
               FROM walten_sessions s ORDER BY s.updated_at DESC, s.id DESC"""
        ).fetchall()
    return {
        "name": walten_module.walten_name(),
        "icon": walten_module.walten_icon(),
        "claude_cli": claude_available(),
        "git": walten_module.git_available(),
        "sessions": [WaltenSession(**_walten_session_dict(row, row["n"])) for row in rows],
    }


@app.post("/api/walten/sessions", response_model=WaltenSessionDetail, status_code=201)
def create_walten_session(payload: WaltenSessionCreate) -> WaltenSessionDetail:
    with get_db() as conn:
        # Timestamps are written with the same helper everywhere. SQLite's own
        # datetime('now') renders "YYYY-MM-DD HH:MM:SS", which sorts below the
        # ISO strings _now() produces, so a mix of the two ordered new
        # conversations *below* older ones.
        stamp = _now()
        cur = conn.execute(
            """INSERT INTO walten_sessions
                   (title, mode, model, context_files, context_urls, created_at, updated_at)
               VALUES (?, ?, ?, '[]', '[]', ?, ?)""",
            (payload.title or "New session", payload.mode, payload.model, stamp, stamp),
        )
        session_id = cur.lastrowid
    return get_walten_session(session_id)


@app.get("/api/walten/sessions/{session_id}", response_model=WaltenSessionDetail)
def get_walten_session(session_id: int) -> WaltenSessionDetail:
    with get_db() as conn:
        row = _walten_session_row(conn, session_id)
        messages = conn.execute(
            "SELECT * FROM walten_messages WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
    git_state = walten_module.working_state()
    detail = _walten_session_dict(row, len(messages))
    detail["messages"] = [WaltenMessage(**_walten_message_dict(m, git_state)) for m in messages]
    detail["running"] = walten_module.is_running(session_id)
    detail["live"] = walten_module.live_state(session_id)
    return WaltenSessionDetail(**detail)


@app.patch("/api/walten/sessions/{session_id}", response_model=WaltenSessionDetail)
def update_walten_session(session_id: int, payload: WaltenSessionUpdate) -> WaltenSessionDetail:
    data = payload.model_dump(exclude_unset=True)
    values: dict[str, Any] = {}
    for field in ("title", "mode", "model"):
        if field in data and data[field]:
            values[field] = data[field]
    for field in ("context_files", "context_urls"):
        if field in data:
            values[field] = json.dumps([x for x in (data[field] or []) if str(x).strip()])
    values["updated_at"] = _now()

    with get_db() as conn:
        _walten_session_row(conn, session_id)
        _apply_updates(conn, "walten_sessions", session_id, values)
    return get_walten_session(session_id)


@app.delete("/api/walten/sessions/{session_id}", status_code=204)
def delete_walten_session(session_id: int) -> None:
    with get_db() as conn:
        if conn.execute("DELETE FROM walten_sessions WHERE id = ?", (session_id,)).rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")


def _record_turn(session_id: int, outcome: dict[str, Any]) -> None:
    """Persist a finished turn and carry the CLI session id forward."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO walten_messages
                   (session_id, role, phase, content, tool_calls, cost_usd, duration_ms,
                    tokens_in, tokens_out, needs_approval, error)
               VALUES (?, 'assistant', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (session_id, outcome["phase"], outcome["content"], json.dumps(outcome["tool_calls"]),
             outcome["cost_usd"], outcome["duration_ms"], outcome["tokens_in"],
             outcome["tokens_out"], int(outcome["needs_approval"]), outcome["error"]),
        )
        conn.execute(
            "UPDATE walten_sessions SET claude_session_id = COALESCE(?, claude_session_id), updated_at = ? WHERE id = ?",
            (outcome.get("claude_session_id"), _now(), session_id),
        )


async def _start_turn(session_id: int, prompt: str, phase: str) -> None:
    with get_db() as conn:
        row = _walten_session_row(conn, session_id)
    await walten_module.run_turn(
        session=dict(row), prompt=prompt, phase=phase,
        on_finish=lambda outcome: _record_turn(session_id, outcome),
    )


@app.post("/api/walten/sessions/{session_id}/messages", response_model=WaltenSessionDetail)
async def send_walten_message(
    session_id: int, payload: WaltenPrompt, background: BackgroundTasks
) -> WaltenSessionDetail:
    """Ask the agent something. The turn runs read-only; poll the session for progress."""
    if walten_module.is_running(session_id):
        raise HTTPException(status_code=409, detail="This session is already running a turn")

    # Commit the tree before the turn starts, so this message is a restore point
    # even if the agent never asks for approval. Nothing to commit is fine: HEAD
    # already describes the state being recorded.
    mark = walten_module.checkpoint(payload.prompt.strip().split("\n")[0])
    if mark.get("warning"):
        logger.warning("Walten checkpoint: %s", mark["warning"])

    with get_db() as conn:
        row = _walten_session_row(conn, session_id)
        conn.execute(
            """INSERT INTO walten_messages (session_id, role, phase, content, snapshot_sha, snapshot_tree)
               VALUES (?, 'user', 'plan', ?, ?, ?)""",
            (session_id, payload.prompt, mark.get("commit"), mark.get("tree")),
        )
        # Name the session after its first instruction.
        if row["title"] == "New session":
            conn.execute(
                "UPDATE walten_sessions SET title = ? WHERE id = ?",
                (payload.prompt.strip().split("\n")[0][:60], session_id),
            )

    background.add_task(_start_turn, session_id, payload.prompt, "plan")
    return get_walten_session(session_id)


@app.post("/api/walten/sessions/{session_id}/approve", response_model=WaltenSessionDetail)
async def approve_walten_plan(session_id: int, background: BackgroundTasks) -> WaltenSessionDetail:
    """Approve the pending plan and resume the same conversation with write access."""
    if walten_module.is_running(session_id):
        raise HTTPException(status_code=409, detail="This session is already running a turn")

    with get_db() as conn:
        row = _walten_session_row(conn, session_id)
        pending = conn.execute(
            """SELECT * FROM walten_messages
               WHERE session_id = ? AND needs_approval = 1 AND resolved = 0
               ORDER BY id DESC LIMIT 1""",
            (session_id,),
        ).fetchone()
        if pending is None:
            raise HTTPException(status_code=409, detail="Nothing is waiting for approval")
        conn.execute("UPDATE walten_messages SET resolved = 1 WHERE id = ?", (pending["id"],))

    if row["mode"] == "engineer":
        warning = walten_module.snapshot(row["title"])
        if warning:
            logger.warning("Walten snapshot: %s", warning)

    background.add_task(
        _start_turn, session_id,
        "Approved. Carry out exactly what you described, nothing more. "
        "Report what you actually changed.",
        "apply",
    )
    return get_walten_session(session_id)


@app.post("/api/walten/sessions/{session_id}/reject", response_model=WaltenSessionDetail)
def reject_walten_plan(session_id: int) -> WaltenSessionDetail:
    with get_db() as conn:
        _walten_session_row(conn, session_id)
        conn.execute(
            """UPDATE walten_messages SET resolved = 1
               WHERE session_id = ? AND needs_approval = 1 AND resolved = 0""",
            (session_id,),
        )
    return get_walten_session(session_id)


def _walten_user_message(conn: sqlite3.Connection, session_id: int, message_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM walten_messages WHERE id = ? AND session_id = ? AND role = 'user'",
        (message_id, session_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Message {message_id} not found in this conversation")
    return row


@app.get("/api/walten/sessions/{session_id}/messages/{message_id}/undo", response_model=WaltenUndoPreview)
def preview_walten_undo(session_id: int, message_id: int) -> WaltenUndoPreview:
    """What undoing back to this message would change, asked before confirming."""
    with get_db() as conn:
        row = _walten_user_message(conn, session_id, message_id)
        later = conn.execute(
            "SELECT COUNT(*) AS n FROM walten_messages WHERE session_id = ? AND role = 'user' AND id > ?",
            (session_id, message_id),
        ).fetchone()["n"]

    if not row["snapshot_tree"]:
        return WaltenUndoPreview(error="This message was sent before restore points were recorded.")
    files = walten_module.changes_since(row["snapshot_tree"])
    return WaltenUndoPreview(
        can_undo=bool(files), count=len(files), files=files[:12], later_messages=later,
    )


@app.post("/api/walten/sessions/{session_id}/messages/{message_id}/undo", response_model=WaltenUndoResult)
def undo_walten_message(session_id: int, message_id: int) -> WaltenUndoResult:
    """Restore the project files to the checkpoint taken when this was sent."""
    if walten_module.is_running(session_id):
        raise HTTPException(status_code=409, detail="Stop the running turn before undoing")

    with get_db() as conn:
        row = _walten_user_message(conn, session_id, message_id)

    result = walten_module.restore(row["snapshot_tree"], row["content"] or "a message")
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])
    changed = result["changed"]
    logger.info("Walten undo to %s restored %d file(s)", row["snapshot_sha"], len(changed))
    return WaltenUndoResult(ok=True, count=len(changed), files=changed[:12])


@app.post("/api/walten/sessions/{session_id}/stop", response_model=WaltenSessionDetail)
async def stop_walten_turn(session_id: int) -> WaltenSessionDetail:
    await walten_module.cancel(session_id)
    return get_walten_session(session_id)


@app.post("/api/walten/sessions/{session_id}/context", response_model=WaltenSessionDetail)
async def upload_walten_context(session_id: int, file: UploadFile = File(...)) -> WaltenSessionDetail:
    """Attach an uploaded file to the session's context."""
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File is larger than {MAX_UPLOAD_BYTES // 1_000_000} MB")

    with get_db() as conn:
        row = _walten_session_row(conn, session_id)

    # `.name` strips directories, but ".." and "." survive it intact and would
    # resolve to the directory itself rather than a file inside it.
    safe = Path(file.filename or "upload.txt").name
    if safe in ("", ".", ".."):
        safe = "upload.txt"
    target_dir = walten_module.CONTEXT_DIR / str(session_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / safe).write_bytes(content)

    relative = str((target_dir / safe).relative_to(walten_module.PROJECT_ROOT))
    files = sorted({*_json_list(row["context_files"]), relative})
    with get_db() as conn:
        conn.execute(
            "UPDATE walten_sessions SET context_files = ?, updated_at = ? WHERE id = ?",
            (json.dumps(files), _now(), session_id),
        )
    return get_walten_session(session_id)


# -------------------------------------------------------------------------- settings

@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    values = {key: value for key, value in all_settings().items() if not key.startswith("resume_")}
    values.pop("last_run", None)
    return {
        "settings": values,
        "cron_schedule": scheduler_module.current_cron(),
        "next_run": scheduler_module.next_run_time(),
        "claude_cli": claude_available(),
        "claude_version": claude_version(),
        "claude_path": claude_bin(),
        "database": str(DB_PATH),
        "resume": resume_status(),
    }


@app.patch("/api/settings")
def update_settings(payload: SettingsUpdate) -> dict[str, Any]:
    data = payload.model_dump(exclude_unset=True, exclude_none=True)
    unknown = set(data) - MUTABLE_SETTINGS
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown settings: {', '.join(sorted(unknown))}")

    if "cron_schedule" in data:
        try:
            scheduler_module.reschedule(str(data.pop("cron_schedule")))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid cron expression: {exc}") from exc
    for key, value in data.items():
        set_setting(key, "1" if value is True else "0" if value is False else str(value))
    return get_settings()


@app.post("/api/settings/claude-path")
def check_claude_path(payload: dict[str, Any]) -> dict[str, Any]:
    """Probe a candidate CLI path and save it when it works.

    An empty path clears the override and falls back to PATH / .env.
    """
    candidate = str(payload.get("path") or "").strip()
    if not candidate:
        set_setting("claude_bin", "")
        return {"ok": claude_available(), "path": claude_bin(), "version": claude_version()}

    version = claude_version(candidate)
    if version is None:
        raise HTTPException(
            status_code=400,
            detail=f"`{candidate}` could not be run. Give the full path to the claude binary.",
        )
    set_setting("claude_bin", candidate)
    return {"ok": True, "path": candidate, "version": version}


@app.get("/api/settings/resume", response_model=ResumeStatus)
def get_resume() -> ResumeStatus:
    return ResumeStatus(**resume_status())


@app.post("/api/settings/resume", response_model=ResumeStatus)
async def upload_resume(file: UploadFile = File(...)) -> ResumeStatus:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File is larger than {MAX_UPLOAD_BYTES // 1_000_000} MB")
    try:
        status = save_resume(file.filename or "resume.pdf", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ResumeStatus(**status)


# ----------------------------------------------------------------- the built UI
#
# In a normal install there is one process on one port: uvicorn serves the API
# under /api and the compiled React bundle everywhere else. The Vite dev server
# is only for development, where it proxies /api back here.
#
# This block must stay at the bottom of the file. The catch-all matches any path
# that is not already a route, so anything registered after it would be shadowed.

DIST_DIR = PROJECT_ROOT / "frontend" / "dist"


@app.get("/")
def root() -> Any:
    if not DIST_DIR.is_dir():
        return {
            "name": "Opportunity Tracker API",
            "docs": "/docs",
            "health": "/api/health",
            "hint": "The UI is not built. Run: cd frontend && npm run build",
        }
    return FileResponse(DIST_DIR / "index.html")


if DIST_DIR.is_dir():
    # Hashed bundles never change under a given name, so they are safe to cache
    # hard; index.html must not be, or an upgrade keeps serving the old one.
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")

    for extra in ("fonts", "favicon.svg", "favicon.ico"):
        target = DIST_DIR / extra
        if target.is_dir():
            app.mount(f"/{extra}", StaticFiles(directory=target), name=extra)

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> Any:
        """Hand any unmatched path to the client-side router.

        React Router owns /opportunities, /settings/appearance and the rest;
        a hard refresh on one of those reaches the server, which has no such
        route and would otherwise 404. Real misses under /api still 404,
        because those routes are registered above this one.
        """
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="No such API route")
        # A request for a file that genuinely is not there should say so rather
        # than silently returning the HTML shell.
        candidate = (DIST_DIR / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(DIST_DIR.resolve()):
            return FileResponse(candidate)
        if "." in full_path.rsplit("/", 1)[-1]:
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(DIST_DIR / "index.html")
