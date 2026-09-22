"""Claude-powered discovery of new job boards, career pages and research programs.

Runs a headless `claude -p` session with web search enabled so proposals reflect
pages that exist today rather than the model's training data.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlparse

from claude_cli import ClaudeCallError, ClaudeUnavailable, extract_json, run_claude
from database import get_db

logger = logging.getLogger(__name__)

VALID_TYPES = {"job_board", "company_careers", "research_program", "aggregator", "university", "government"}
VALID_METHODS = {"html", "api", "search_query"}
MAX_RESUME_CHARS = 4000

SYSTEM_PROMPT = """You are a research assistant that finds job boards, company career pages,
research program listings and fellowship pages relevant to a Computer Science / Quantum
Engineering student.

Use web search to confirm that every page you propose exists right now and is a LISTING page
(a page that lists multiple openings), not a single job post, a news article or a homepage.

Return ONLY a valid JSON array. Each element must have exactly these fields:
{
  "name": "short human-readable source name",
  "url": "https://... the listings page",
  "type": "job_board|company_careers|research_program|aggregator|university|government",
  "scrape_method": "html|api|search_query",
  "rationale": "one or two sentences on why this source fits this student",
  "confidence": float between 0.0 and 1.0
}
Do not propose any URL that appears in the existing-sources list.
Do not include any text outside the JSON array."""


def _clean_str(value: Any, limit: int) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _normalize(entry: dict[str, Any], blocked: set[str]) -> Optional[dict[str, Any]]:
    url = _clean_str(entry.get("url"), 1000)
    name = _clean_str(entry.get("name"), 200)
    if not url or not name:
        return None

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    url = url.split("#")[0].rstrip("/") or url
    if url.lower() in blocked:
        return None

    type_ = str(entry.get("type", "")).strip().lower()
    method = str(entry.get("scrape_method", "html")).strip().lower()
    try:
        confidence = round(max(0.0, min(1.0, float(entry.get("confidence", 0.5)))), 2)
    except (TypeError, ValueError):
        confidence = 0.5

    return {
        "name": name,
        "url": url,
        "type": type_ if type_ in VALID_TYPES else "job_board",
        "scrape_method": method if method in VALID_METHODS else "html",
        "rationale": _clean_str(entry.get("rationale"), 800),
        "confidence": confidence,
    }


def known_urls() -> list[str]:
    """Every URL already tracked as a source or already proposed."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT url FROM sources UNION SELECT url FROM source_proposals WHERE status != 'rejected'"
        ).fetchall()
    return [row["url"] for row in rows]


def discover_sources(
    existing_urls: list[str],
    resume_text: Optional[str],
    *,
    count: int = 12,
    focus: Optional[str] = None,
    model: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Ask Claude for new sources. Returns normalised proposal dicts (not yet saved)."""
    blocked = {url.split("#")[0].rstrip("/").lower() for url in existing_urls}

    prompt_parts = [
        f"Find {count} new sources (aim for {count}, never fewer than {max(1, count - 2)}).",
        "Focus on quantum computing, quantum engineering, quantum information science and "
        "adjacent computer science roles: internships, new-grad roles, REUs, national lab "
        "programs, fellowships and graduate programs.",
    ]
    if focus:
        prompt_parts.append(f"Extra emphasis from the user: {focus}")
    prompt_parts.append(
        "Existing sources to avoid duplicating:\n"
        + "\n".join(f"- {url}" for url in sorted(existing_urls)[:200])
    )
    if resume_text:
        prompt_parts.append(f"Student resume for context:\n{resume_text[:MAX_RESUME_CHARS]}")

    try:
        response = run_claude(
            "\n\n".join(prompt_parts),
            system=SYSTEM_PROMPT,
            model=model,
            allowed_tools=["WebSearch", "WebFetch"],
            timeout=600,
        )
        data = extract_json(response)
    except (ClaudeUnavailable, ClaudeCallError, ValueError) as exc:
        logger.warning("Source discovery failed: %s", exc)
        raise

    if isinstance(data, dict):
        data = data.get("sources") or data.get("proposals") or data.get("results") or []
    if not isinstance(data, list):
        raise ValueError("Claude did not return a JSON array of proposals")

    proposals: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in data:
        if not isinstance(entry, dict):
            continue
        normalized = _normalize(entry, blocked)
        if normalized and normalized["url"].lower() not in seen:
            seen.add(normalized["url"].lower())
            proposals.append(normalized)

    logger.info("Discovered %d new source proposal(s)", len(proposals))
    return proposals


def save_proposals(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist proposals to `source_proposals`, skipping ones already pending."""
    saved: list[dict[str, Any]] = []
    with get_db() as conn:
        for proposal in proposals:
            duplicate = conn.execute(
                "SELECT 1 FROM source_proposals WHERE url = ? AND status = 'pending'", (proposal["url"],)
            ).fetchone()
            if duplicate:
                continue
            cur = conn.execute(
                """INSERT INTO source_proposals (name, url, type, scrape_method, rationale, confidence, status)
                   VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
                (
                    proposal["name"],
                    proposal["url"],
                    proposal["type"],
                    proposal["scrape_method"],
                    proposal.get("rationale"),
                    proposal.get("confidence"),
                ),
            )
            row = conn.execute("SELECT * FROM source_proposals WHERE id = ?", (cur.lastrowid,)).fetchone()
            saved.append(dict(row))
    return saved


def run_discovery(count: int = 12, focus: Optional[str] = None) -> list[dict[str, Any]]:
    """Discover and persist in one step. Used by the API and the cron task."""
    from resume_loader import get_resume_text

    proposals = discover_sources(known_urls(), get_resume_text(), count=count, focus=focus)
    return save_proposals(proposals)


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO)
    from database import init_db

    init_db()
    print(json.dumps(run_discovery(count=4), indent=2))
