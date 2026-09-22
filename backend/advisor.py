"""Resume-aware analysis: per-listing fit advice and an aggregate role landscape.

Both features run through the headless `claude -p` bridge, same as the classifier.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from claude_cli import ClaudeCallError, ClaudeUnavailable, extract_json, run_claude
from database import get_db
from resume_loader import get_resume_text, resume_status

logger = logging.getLogger(__name__)

MAX_RESUME_CHARS = 9000
MAX_LISTING_CHARS = 5000
MAX_LANDSCAPE_LISTINGS = 40

REQUIREMENT_STATUSES = {"met", "partial", "gap", "unknown"}
PRIORITIES = {"high", "medium", "low"}


class AdvisorError(RuntimeError):
    """Raised when analysis cannot be produced."""


# --------------------------------------------------------------------------- prompts

FIT_SYSTEM_PROMPT = """You are a resume coach for a Computer Science / Quantum Engineering student.
You will be given one job or research listing and the student's resume.

Be concrete and honest. Never invent experience the student does not have: every suggested
resume line must be supported by something already in the resume, reframed or emphasised
differently. If a requirement is genuinely unmet, say so and suggest how to close it.

Return ONLY a valid JSON object with exactly these fields:
{
  "fit_summary": "2-3 sentences on how well this resume, as written, fits this listing",
  "fit_score": float between 1.0 and 10.0 for how ready the resume is for this listing today,
  "requirements": [
    {
      "requirement": "a single requirement stated or clearly implied by the listing",
      "importance": "required|preferred|nice_to_have",
      "status": "met|partial|gap",
      "evidence": "what in the resume supports this, or what is missing"
    }
  ],
  "adjustments": [
    {
      "section": "which resume section to change, e.g. 'Projects — Delphi oracle compiler'",
      "current": "how it reads now, or null if this is a new addition",
      "suggested": "the concrete replacement or addition text",
      "rationale": "why this helps for THIS listing",
      "priority": "high|medium|low"
    }
  ],
  "keywords": ["exact terms from the listing worth mirroring in the resume"],
  "talking_points": ["points to raise in a cover letter or interview for this role"]
}
Cover every significant requirement in the listing. Give 3-8 adjustments, ordered most
impactful first. Do not include any text outside the JSON object."""

LANDSCAPE_SYSTEM_PROMPT = """You are a career strategist for a Computer Science / Quantum Engineering student.
You will be given a set of job and research listings the student is tracking, plus their resume.

Analyse the set as a whole, not listing by listing. Identify what these roles actually ask for,
where the student's existing experience already satisfies it, and where the real gaps are.
Be honest about gaps and specific about what to do next. Never invent experience.

Return ONLY a valid JSON object with exactly these fields:
{
  "summary": "3-5 sentences describing the shape of this opportunity set and how the student stands against it",
  "role_groups": [
    {
      "label": "a natural grouping, e.g. 'Quantum software / algorithms'",
      "count": integer number of listings in this group,
      "description": "what these roles do and what they screen for",
      "example_titles": ["two or three listing titles from this group"]
    }
  ],
  "requirements": [
    {
      "requirement": "a requirement that recurs across these listings",
      "frequency": "how widely it appears, e.g. 'most roles' or '7 of 12 listings'",
      "status": "met|partial|gap",
      "evidence": "what in the resume supports it",
      "gap_note": "what is missing and how to close it, or null when fully met"
    }
  ],
  "recommended_skills": [
    {
      "skill": "a skill worth developing next",
      "why": "why it matters for this specific opportunity set",
      "unlocks": "which roles or groups it opens up",
      "effort": "a realistic time estimate, e.g. 'a weekend' or 'one term'",
      "priority": "high|medium|low"
    }
  ],
  "strengths": ["resume strengths that are genuinely differentiating for this set of roles"]
}
Order requirements by how widely they recur, and recommended_skills by priority.
Do not include any text outside the JSON object."""


# --------------------------------------------------------------------- normalisation

def _text(value: Any, limit: int = 1200) -> Optional[str]:
    if value is None:
        return None
    out = str(value).strip()
    if not out or out.lower() in {"null", "none", "n/a"}:
        return None
    return out[:limit]


def _str_list(value: Any, limit: int = 25) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    items = [t for t in (_text(item, 400) for item in value) if t]
    return items[:limit]


def _score(value: Any) -> Optional[float]:
    try:
        return round(max(0.0, min(10.0, float(value))), 1)
    except (TypeError, ValueError):
        return None


def _enum(value: Any, allowed: set[str], default: str) -> str:
    candidate = str(value or "").strip().lower().replace(" ", "_")
    return candidate if candidate in allowed else default


def _normalize_fit(data: dict[str, Any]) -> dict[str, Any]:
    requirements = []
    for entry in data.get("requirements") or []:
        if not isinstance(entry, dict):
            continue
        requirement = _text(entry.get("requirement"), 400)
        if not requirement:
            continue
        requirements.append(
            {
                "requirement": requirement,
                "importance": _enum(entry.get("importance"), {"required", "preferred", "nice_to_have"}, "preferred"),
                "status": _enum(entry.get("status"), REQUIREMENT_STATUSES, "unknown"),
                "evidence": _text(entry.get("evidence"), 600),
            }
        )

    adjustments = []
    for entry in data.get("adjustments") or []:
        if not isinstance(entry, dict):
            continue
        suggested = _text(entry.get("suggested"), 900)
        if not suggested:
            continue
        adjustments.append(
            {
                "section": _text(entry.get("section"), 200) or "Resume",
                "current": _text(entry.get("current"), 900),
                "suggested": suggested,
                "rationale": _text(entry.get("rationale"), 600),
                "priority": _enum(entry.get("priority"), PRIORITIES, "medium"),
            }
        )
    order = {"high": 0, "medium": 1, "low": 2}
    adjustments.sort(key=lambda item: order[item["priority"]])

    return {
        "fit_summary": _text(data.get("fit_summary"), 1500),
        "fit_score": _score(data.get("fit_score")),
        "requirements": requirements[:30],
        "adjustments": adjustments[:12],
        "keywords": _str_list(data.get("keywords"), 25),
        "talking_points": _str_list(data.get("talking_points"), 12),
    }


def _normalize_landscape(data: dict[str, Any]) -> dict[str, Any]:
    groups = []
    for entry in data.get("role_groups") or []:
        if not isinstance(entry, dict):
            continue
        label = _text(entry.get("label"), 200)
        if not label:
            continue
        try:
            count = max(0, int(entry.get("count", 0)))
        except (TypeError, ValueError):
            count = 0
        groups.append(
            {
                "label": label,
                "count": count,
                "description": _text(entry.get("description"), 800),
                "example_titles": _str_list(entry.get("example_titles"), 5),
            }
        )

    requirements = []
    for entry in data.get("requirements") or []:
        if not isinstance(entry, dict):
            continue
        requirement = _text(entry.get("requirement"), 400)
        if not requirement:
            continue
        requirements.append(
            {
                "requirement": requirement,
                "frequency": _text(entry.get("frequency"), 120),
                "status": _enum(entry.get("status"), REQUIREMENT_STATUSES, "unknown"),
                "evidence": _text(entry.get("evidence"), 600),
                "gap_note": _text(entry.get("gap_note"), 600),
            }
        )

    skills = []
    for entry in data.get("recommended_skills") or []:
        if not isinstance(entry, dict):
            continue
        skill = _text(entry.get("skill"), 200)
        if not skill:
            continue
        skills.append(
            {
                "skill": skill,
                "why": _text(entry.get("why"), 600),
                "unlocks": _text(entry.get("unlocks"), 400),
                "effort": _text(entry.get("effort"), 120),
                "priority": _enum(entry.get("priority"), PRIORITIES, "medium"),
            }
        )
    order = {"high": 0, "medium": 1, "low": 2}
    skills.sort(key=lambda item: order[item["priority"]])

    return {
        "summary": _text(data.get("summary"), 2500),
        "role_groups": groups[:10],
        "requirements": requirements[:30],
        "recommended_skills": skills[:15],
        "strengths": _str_list(data.get("strengths"), 12),
    }


def _resume_or_raise() -> str:
    resume = get_resume_text()
    if not resume:
        raise AdvisorError(
            "No resume is loaded. Upload one in Settings — this analysis is entirely resume-relative."
        )
    return resume[:MAX_RESUME_CHARS]


def _listing_block(row: Any) -> str:
    parts = [
        f"Title: {row['title']}",
        f"Organization: {row['organization']}",
        f"Type: {row['type']}",
    ]
    if row["location"]:
        parts.append(f"Location: {row['location']}{' (remote)' if row['remote'] else ''}")
    if row["experience_level"]:
        parts.append(f"Experience level: {row['experience_level']}")
    if row["deadline"]:
        parts.append(f"Deadline: {row['deadline']}")
    if row["description"]:
        parts.append(f"Description: {row['description']}")
    for field in ("skill_matches", "tags"):
        try:
            values = json.loads(row[field] or "[]")
        except (TypeError, ValueError):
            values = []
        if values:
            parts.append(f"{field.replace('_', ' ').capitalize()}: {', '.join(map(str, values))}")
    parts.append(f"URL: {row['url']}")
    return "\n".join(parts)


# ---------------------------------------------------------------- per-listing advice

def generate_resume_advice(opportunity_id: int, *, model: Optional[str] = None) -> dict[str, Any]:
    """Ask Claude how to adjust the resume for one listing, and cache the result."""
    resume = _resume_or_raise()

    with get_db() as conn:
        row = conn.execute("SELECT * FROM opportunities WHERE id = ?", (opportunity_id,)).fetchone()
    if row is None:
        raise AdvisorError(f"Opportunity {opportunity_id} not found")

    prompt = (
        f"Listing:\n{_listing_block(row)[:MAX_LISTING_CHARS]}\n\n"
        f"Student resume:\n{resume}"
    )

    try:
        data = extract_json(run_claude(prompt, system=FIT_SYSTEM_PROMPT, model=model, timeout=300))
    except (ClaudeUnavailable, ClaudeCallError, ValueError) as exc:
        raise AdvisorError(f"Could not generate resume advice: {exc}") from exc
    if not isinstance(data, dict):
        raise AdvisorError("Claude did not return a JSON object")

    advice = _normalize_fit(data)
    filename = resume_status().get("filename")
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with get_db() as conn:
        conn.execute(
            """INSERT INTO resume_advice (
                   opportunity_id, generated_at, resume_filename, fit_summary, fit_score,
                   requirements, adjustments, keywords, talking_points
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(opportunity_id) DO UPDATE SET
                   generated_at = excluded.generated_at,
                   resume_filename = excluded.resume_filename,
                   fit_summary = excluded.fit_summary,
                   fit_score = excluded.fit_score,
                   requirements = excluded.requirements,
                   adjustments = excluded.adjustments,
                   keywords = excluded.keywords,
                   talking_points = excluded.talking_points""",
            (
                opportunity_id,
                generated_at,
                filename,
                advice["fit_summary"],
                advice["fit_score"],
                json.dumps(advice["requirements"]),
                json.dumps(advice["adjustments"]),
                json.dumps(advice["keywords"]),
                json.dumps(advice["talking_points"]),
            ),
        )

    logger.info(
        "Generated resume advice for opportunity %s (%d requirements, %d adjustments)",
        opportunity_id,
        len(advice["requirements"]),
        len(advice["adjustments"]),
    )
    return {
        "opportunity_id": opportunity_id,
        "generated_at": generated_at,
        "resume_filename": filename,
        "stale": False,
        **advice,
    }


def get_resume_advice(opportunity_id: int) -> Optional[dict[str, Any]]:
    """Return cached advice, flagged stale when the resume changed since it was made."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM resume_advice WHERE opportunity_id = ?", (opportunity_id,)
        ).fetchone()
    if row is None:
        return None

    def parsed(field: str) -> list:
        try:
            value = json.loads(row[field] or "[]")
        except (TypeError, ValueError):
            return []
        return value if isinstance(value, list) else []

    current_resume = resume_status().get("filename")
    return {
        "opportunity_id": row["opportunity_id"],
        "generated_at": row["generated_at"],
        "resume_filename": row["resume_filename"],
        "stale": bool(current_resume and row["resume_filename"] and current_resume != row["resume_filename"]),
        "fit_summary": row["fit_summary"],
        "fit_score": row["fit_score"],
        "requirements": parsed("requirements"),
        "adjustments": parsed("adjustments"),
        "keywords": parsed("keywords"),
        "talking_points": parsed("talking_points"),
    }


# ------------------------------------------------------------- aggregate landscape

def generate_role_analysis(
    rows: Iterable[Any],
    *,
    scope: str = "All active opportunities",
    model: Optional[str] = None,
) -> dict[str, Any]:
    """Summarise a set of listings: what they ask for, what the resume covers, what to learn."""
    resume = _resume_or_raise()
    listings = list(rows)[:MAX_LANDSCAPE_LISTINGS]
    if not listings:
        raise AdvisorError("There are no opportunities to analyse yet. Run the scraper first.")

    blocks = [f"--- LISTING {index + 1} ---\n{_listing_block(row)}" for index, row in enumerate(listings)]
    prompt = (
        f"Scope: {scope}\n"
        f"{len(listings)} listings the student is tracking:\n\n"
        + "\n\n".join(blocks)
        + f"\n\nStudent resume:\n{resume}"
    )

    try:
        data = extract_json(run_claude(prompt, system=LANDSCAPE_SYSTEM_PROMPT, model=model, timeout=600))
    except (ClaudeUnavailable, ClaudeCallError, ValueError) as exc:
        raise AdvisorError(f"Could not generate role analysis: {exc}") from exc
    if not isinstance(data, dict):
        raise AdvisorError("Claude did not return a JSON object")

    analysis = _normalize_landscape(data)
    filename = resume_status().get("filename")
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO role_analyses (
                   generated_at, scope, opportunity_count, resume_filename, summary,
                   role_groups, requirements, recommended_skills, strengths
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                generated_at,
                scope,
                len(listings),
                filename,
                analysis["summary"],
                json.dumps(analysis["role_groups"]),
                json.dumps(analysis["requirements"]),
                json.dumps(analysis["recommended_skills"]),
                json.dumps(analysis["strengths"]),
            ),
        )
        analysis_id = cur.lastrowid

    logger.info(
        "Generated role analysis %s over %d listings (%d requirements, %d skills)",
        analysis_id,
        len(listings),
        len(analysis["requirements"]),
        len(analysis["recommended_skills"]),
    )
    return {
        "id": analysis_id,
        "generated_at": generated_at,
        "scope": scope,
        "opportunity_count": len(listings),
        "resume_filename": filename,
        **analysis,
    }


def _analysis_row_to_dict(row) -> dict[str, Any]:
    def parsed(field: str) -> list:
        try:
            value = json.loads(row[field] or "[]")
        except (TypeError, ValueError):
            return []
        return value if isinstance(value, list) else []

    return {
        "id": row["id"],
        "generated_at": row["generated_at"],
        "edited_at": row["edited_at"] if "edited_at" in row.keys() else None,
        "scope": row["scope"],
        "opportunity_count": row["opportunity_count"],
        "resume_filename": row["resume_filename"],
        "summary": row["summary"],
        "role_groups": parsed("role_groups"),
        "requirements": parsed("requirements"),
        "recommended_skills": parsed("recommended_skills"),
        "strengths": parsed("strengths"),
    }


def get_latest_role_analysis() -> Optional[dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM role_analyses ORDER BY id DESC LIMIT 1").fetchone()
    return _analysis_row_to_dict(row) if row is not None else None


def get_role_analysis(analysis_id: int) -> Optional[dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM role_analyses WHERE id = ?", (analysis_id,)).fetchone()
    return _analysis_row_to_dict(row) if row is not None else None


# Columns the user may overwrite by hand, and whether they are stored as JSON.
EDITABLE_ANALYSIS_FIELDS = {
    "scope": False,
    "summary": False,
    "role_groups": True,
    "requirements": True,
    "recommended_skills": True,
    "strengths": True,
}


def update_role_analysis(analysis_id: int, values: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Replace hand-edited fields on a stored analysis.

    Stamps `edited_at` so the UI can say the analysis no longer matches verbatim
    what Claude produced.
    """
    assignments: list[str] = []
    params: list[Any] = []
    for field, is_json in EDITABLE_ANALYSIS_FIELDS.items():
        if field not in values:
            continue
        assignments.append(f"{field} = ?")
        params.append(json.dumps(values[field] or []) if is_json else values[field])

    if not assignments:
        return get_role_analysis(analysis_id)

    assignments.append("edited_at = ?")
    params.append(datetime.now(timezone.utc).isoformat(timespec="seconds"))
    params.append(analysis_id)

    with get_db() as conn:
        cur = conn.execute(
            f"UPDATE role_analyses SET {', '.join(assignments)} WHERE id = ?", params
        )
        if cur.rowcount == 0:
            return None
    return get_role_analysis(analysis_id)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    from database import init_db

    init_db()
    if len(sys.argv) > 1 and sys.argv[1] == "landscape":
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM opportunities WHERE is_active = 1 ORDER BY relevance_score DESC LIMIT 12"
            ).fetchall()
        print(json.dumps(generate_role_analysis(rows, scope="Top 12 by relevance"), indent=2)[:4000])
    else:
        with get_db() as conn:
            row = conn.execute(
                "SELECT id FROM opportunities ORDER BY relevance_score DESC LIMIT 1"
            ).fetchone()
        print(json.dumps(generate_resume_advice(row["id"]), indent=2)[:4000])
