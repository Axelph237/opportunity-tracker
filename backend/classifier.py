"""Claude-powered classification and resume scoring of scraped listings.

All calls go through the headless `claude -p` bridge in `claude_cli`, so this
module never touches the Anthropic API directly and needs no API key.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

from claude_cli import ClaudeCallError, ClaudeUnavailable, run_claude, extract_json

logger = logging.getLogger(__name__)

MAX_LISTING_CHARS = 6000
MAX_RESUME_CHARS = 8000
STRONG_MATCH_THRESHOLD = 7.5

VALID_TYPES = {"internship", "job", "research", "grad_program", "fellowship", "other"}
VALID_LEVELS = {"entry", "mid", "senior", "student", "postdoc", "any"}

SYSTEM_PROMPT = """You are a career opportunity classifier for a Computer Science / Quantum Engineering student.
You will be given the raw text of a job or research listing and the student's resume.
Return ONLY a valid JSON object with exactly these fields:
{
  "title": "string",
  "organization": "string",
  "type": "internship|job|research|grad_program|fellowship|other",
  "location": "string or null",
  "remote": true or false,
  "deadline": "YYYY-MM-DD or descriptive string or null",
  "description": "2-3 sentence summary of the role",
  "experience_level": "entry|mid|senior|student|postdoc|any",
  "relevance_score": float between 1.0 and 10.0,
  "relevance_summary": "one sentence explaining the score relative to this student's resume",
  "skill_matches": ["array", "of", "matching", "skills", "from", "resume"],
  "strong_match": true or false (true if score >= 7.5),
  "tags": ["freeform", "tags", "e.g.", "quantum hardware", "Qiskit", "remote-friendly"]
}
Do not include any text outside the JSON object."""

BATCH_SYSTEM_PROMPT = SYSTEM_PROMPT.replace(
    "Return ONLY a valid JSON object with exactly these fields:",
    "You will receive SEVERAL numbered listings at once. Return ONLY a valid JSON array with one "
    "object per listing, in the same order, each carrying its input \"index\" plus exactly these fields:",
).replace("Do not include any text outside the JSON object.", "Do not include any text outside the JSON array.")

NO_RESUME_NOTE = (
    "(No resume was provided. Score relevance for a general Computer Science / Quantum "
    "Engineering student and say so in relevance_summary.)"
)


# --------------------------------------------------------------------- normalisation

def _clean_str(value: Any, limit: int = 500) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a", "unknown"}:
        return None
    return text[:limit]


def _clean_list(value: Any, limit: int = 20) -> list[str]:
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    if not isinstance(value, (list, tuple)):
        return []
    items: list[str] = []
    for item in value:
        text = _clean_str(item, 80)
        if text and text not in items:
            items.append(text)
    return items[:limit]


def _clean_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(10.0, score)), 1)


def _clean_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"true", "yes", "1", "remote"}


def normalize_result(data: dict[str, Any], url: str, source_name: str = "") -> dict[str, Any]:
    """Coerce a raw Claude response into the shape the database expects."""
    type_ = str(data.get("type", "")).strip().lower()
    level = str(data.get("experience_level", "")).strip().lower()
    score = _clean_score(data.get("relevance_score"))

    return {
        "url": _clean_str(data.get("url"), 1000) or url,
        "title": _clean_str(data.get("title"), 300) or "Untitled listing",
        "organization": _clean_str(data.get("organization"), 200) or (source_name or "Unknown"),
        "type": type_ if type_ in VALID_TYPES else "other",
        "location": _clean_str(data.get("location"), 200),
        "remote": _clean_bool(data.get("remote")),
        "deadline": _clean_str(data.get("deadline"), 100),
        "description": _clean_str(data.get("description"), 2000),
        "experience_level": level if level in VALID_LEVELS else "any",
        "relevance_score": score,
        "relevance_summary": _clean_str(data.get("relevance_summary"), 600),
        "skill_matches": _clean_list(data.get("skill_matches")),
        "strong_match": score >= STRONG_MATCH_THRESHOLD,
        "tags": _clean_list(data.get("tags")),
    }


def _failed_result(url: str, reason: str) -> dict[str, Any]:
    return {
        "url": url,
        "title": "Unclassified listing",
        "organization": "Unknown",
        "type": "other",
        "location": None,
        "remote": False,
        "deadline": None,
        "description": None,
        "experience_level": "any",
        "relevance_score": 0.0,
        "relevance_summary": None,
        "skill_matches": [],
        "strong_match": False,
        "tags": [],
        "error": reason,
    }


def _resume_block(resume_text: Optional[str]) -> str:
    if not resume_text:
        return NO_RESUME_NOTE
    return resume_text[:MAX_RESUME_CHARS]


# ------------------------------------------------------------------------ public API

def classify_opportunity(
    raw_text: str,
    url: str,
    source_name: str,
    resume_text: Optional[str],
    *,
    model: Optional[str] = None,
) -> dict[str, Any]:
    """Classify and score a single listing. Never raises — failures score 0."""
    listing = (raw_text or "").strip()[:MAX_LISTING_CHARS]
    if not listing:
        return _failed_result(url, "empty listing text")

    user_message = (
        f"Listing URL: {url}\n"
        f"Source: {source_name}\n\n"
        f"Listing text:\n{listing}\n\n"
        f"Student resume:\n{_resume_block(resume_text)}"
    )

    try:
        response = run_claude(user_message, system=SYSTEM_PROMPT, model=model)
        data = extract_json(response)
    except (ClaudeUnavailable, ClaudeCallError, ValueError) as exc:
        logger.warning("Classification failed for %s: %s", url, exc)
        return _failed_result(url, str(exc))

    if not isinstance(data, dict):
        return _failed_result(url, "response was not a JSON object")
    return normalize_result(data, url, source_name)


def classify_batch(
    listings: Iterable[dict[str, str]],
    resume_text: Optional[str],
    *,
    source_name: str = "",
    model: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Classify several listings in one headless turn.

    Each listing is a dict with `url` and `text`. Falls back to per-listing calls
    if the batch response cannot be parsed, so a malformed reply never loses work.
    """
    items = [dict(item) for item in listings]
    if not items:
        return []
    if len(items) == 1:
        single = items[0]
        return [classify_opportunity(single.get("text", ""), single.get("url", ""), source_name, resume_text, model=model)]

    blocks: list[str] = []
    per_listing_budget = max(1200, MAX_LISTING_CHARS // max(1, len(items)))
    for index, item in enumerate(items):
        text = (item.get("text") or "").strip()[:per_listing_budget]
        blocks.append(f'--- LISTING index={index} url={item.get("url", "")} ---\n{text}')

    user_message = (
        f"Source: {source_name}\n"
        f"Classify all {len(items)} listings below.\n\n"
        + "\n\n".join(blocks)
        + f"\n\nStudent resume:\n{_resume_block(resume_text)}"
    )

    try:
        response = run_claude(user_message, system=BATCH_SYSTEM_PROMPT, model=model)
        data = extract_json(response)
    except (ClaudeUnavailable, ClaudeCallError, ValueError) as exc:
        logger.warning("Batch classification failed for %s: %s", source_name, exc)
        return [
            classify_opportunity(item.get("text", ""), item.get("url", ""), source_name, resume_text, model=model)
            for item in items
        ]

    if isinstance(data, dict):
        data = data.get("listings") or data.get("results") or [data]
    if not isinstance(data, list):
        logger.warning("Batch response for %s was not a list; falling back", source_name)
        data = []

    by_index: dict[int, dict[str, Any]] = {}
    for position, entry in enumerate(data):
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry.get("index", position))
        except (TypeError, ValueError):
            index = position
        if 0 <= index < len(items):
            by_index.setdefault(index, entry)

    results: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        entry = by_index.get(index)
        url = item.get("url", "")
        if entry is None:
            results.append(_failed_result(url, "missing from batch response"))
        else:
            results.append(normalize_result(entry, url, source_name))
    return results


if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO)
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
    from database import init_db
    from resume_loader import get_resume_text

    init_db()
    SAMPLE = """
    Quantum Computing Research Intern — Summer 2027
    IonQ, College Park, MD (hybrid)
    We are seeking a student intern to work on trapped-ion qubit control software.
    You will write Python tooling, work with Qiskit-style circuit representations,
    and help characterise gate fidelities alongside our hardware team.
    Requirements: currently enrolled in a BS/MS in CS, Physics or a related field;
    strong Python; familiarity with linear algebra and quantum information basics.
    Applications close January 15, 2027.
    """
    result = classify_opportunity(SAMPLE, "https://ionq.com/careers/quantum-intern", "IonQ Careers", get_resume_text())
    print(json.dumps(result, indent=2))
