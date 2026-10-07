"""Job posts: the real advertisement text the rest of the app otherwise lacks.

`opportunities.description` is a two-sentence LLM summary averaging 258
characters, which is far too thin to tailor a resume against. A job post holds
the ad as the board wrote it, plus the three keyword buckets a resume is
screened on.

Pasting is the primary input. Fetching is a convenience that a good share of
job boards refuse outright, so it is never allowed to half-succeed: a blocked
or empty page raises and leaves `raw_text` exactly as it was.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from claude_cli import ClaudeCallError, extract_json, run_claude
from database import get_db
from scraper import USER_AGENT, _clean_text, _main_content

logger = logging.getLogger(__name__)

MAX_POST_CHARS = 20_000
MAX_KEYWORDS = 40
MAX_TERM_CHARS = 120
MAX_VARIANTS = 8
MAX_TITLE_CHARS = 300

FETCH_TIMEOUT = 20.0
KEYWORD_TIMEOUT = 300

# A real ad runs to thousands of characters. Anything near this is a consent
# wall, a JavaScript shell or an error page, and storing it would be worse than
# storing nothing.
MIN_FETCHED_CHARS = 400

BUCKETS = {"technical", "verb", "professional"}

EDITABLE_FIELDS = ("opportunity_id", "title", "organization", "url", "raw_text", "source", "keywords")


class JobPostNotFound(LookupError):
    """Raised when a job post id does not exist."""


class JobPostError(RuntimeError):
    """Raised when a job post cannot be fetched or analysed."""


KEYWORD_SYSTEM_PROMPT = """You are a resume screener's eye, reading one job advertisement on behalf
of a Computer Science / Quantum Engineering student.

Pull out the terms the advertisement itself uses. A resume gets about thirty seconds against the
words in the ad, so mirroring the ad's own wording beats finding a better synonym for it. Never add
a term the ad does not contain, and never generalise a specific tool into its category. If the ad is
short or vague, return fewer terms rather than inventing them.

Return ONLY a valid JSON object with exactly these fields:
{
  "keywords": [
    {
      "term": "the term, worded exactly as the advertisement words it",
      "bucket": "technical|verb|professional",
      "weight": float between 0.0 and 1.0 for how prominent this term is in the advertisement,
      "variants": ["other surface forms of this same term: inflections, plurals, spelled-out or abbreviated versions"]
    }
  ]
}
A "technical" term is a tool, language, method or domain concept. A "verb" is an action the role
performs. A "professional" term is a transferable working skill. Order the list by prominence in the
advertisement, most prominent first, and return at most 40 terms.
Do not include any text outside the JSON object."""


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _json_list(value: Any) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _text(value: Any, limit: int) -> Optional[str]:
    if value is None:
        return None
    out = str(value).strip()
    if not out or out.lower() in {"null", "none", "n/a"}:
        return None
    return out[:limit]


# A garbage bucket or weight falls back to `models.Keyword`'s own defaults
# rather than to a neutral value, so a hand-written keyword and a salvaged one
# describe themselves the same way. Weight only orders the panel; it never
# decides whether a term counts as covered.
def _bucket(value: Any) -> str:
    candidate = str(value or "").strip().lower().replace(" ", "_")
    return candidate if candidate in BUCKETS else "technical"


def _weight(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 2)
    except (TypeError, ValueError):
        return 1.0


def _variants(value: Any, term: str) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    variants: list[str] = []
    seen = {term.casefold()}
    for item in value:
        variant = _text(item, MAX_TERM_CHARS)
        if variant and variant.casefold() not in seen:
            seen.add(variant.casefold())
            variants.append(variant)
    return variants[:MAX_VARIANTS]


def _normalize_keywords(data: Any) -> list[dict[str, Any]]:
    """Rebuild the model's keyword list field by field.

    Every value is treated as missing, wrong-typed or garbage until proven
    otherwise, so an unusable response becomes an empty list rather than a 500.
    The model's ordering is kept: it was asked for prominence order, and there
    is nothing better to sort by.
    """
    raw = data.get("keywords") if isinstance(data, dict) else data
    if not isinstance(raw, (list, tuple)):
        return []

    keywords: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        term = _text(entry.get("term"), MAX_TERM_CHARS)
        if not term or term.casefold() in seen:
            continue
        seen.add(term.casefold())
        keywords.append(
            {
                "term": term,
                "bucket": _bucket(entry.get("bucket")),
                "weight": _weight(entry.get("weight")),
                "variants": _variants(entry.get("variants"), term),
            }
        )
    return keywords[:MAX_KEYWORDS]


def post_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["keywords"] = _json_list(data.get("keywords"))
    return data


def list_posts() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM job_posts ORDER BY updated_at DESC, id DESC").fetchall()
    return [post_dict(row) for row in rows]


def get_post(post_id: int) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM job_posts WHERE id = ?", (post_id,)).fetchone()
    if row is None:
        raise JobPostNotFound(f"Job post {post_id} not found")
    return post_dict(row)


def create_post(values: dict[str, Any]) -> dict[str, Any]:
    title = _text(values.get("title"), MAX_TITLE_CHARS)
    if not title:
        raise ValueError("A job post needs a title.")

    now = _now()
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO job_posts (
                   opportunity_id, title, organization, url, raw_text, source,
                   created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                values.get("opportunity_id"),
                title,
                _text(values.get("organization"), 300),
                _text(values.get("url"), 1000),
                str(values.get("raw_text") or "")[:MAX_POST_CHARS],
                values.get("source") or "pasted",
                now,
                now,
            ),
        )
        post_id = cur.lastrowid
    return get_post(post_id)


def update_post(post_id: int, values: dict[str, Any]) -> dict[str, Any]:
    changes = {key: value for key, value in values.items() if key in EDITABLE_FIELDS}
    if "title" in changes:
        title = _text(changes["title"], MAX_TITLE_CHARS)
        if not title:
            raise ValueError("A job post needs a title.")
        changes["title"] = title
    if "raw_text" in changes:
        changes["raw_text"] = str(changes["raw_text"] or "")[:MAX_POST_CHARS]
    if "keywords" in changes:
        changes["keywords"] = json.dumps(_normalize_keywords(changes["keywords"]))
    if not changes:
        return get_post(post_id)

    with get_db() as conn:
        if conn.execute("SELECT 1 FROM job_posts WHERE id = ?", (post_id,)).fetchone() is None:
            raise JobPostNotFound(f"Job post {post_id} not found")
        assignments = ", ".join(f"{column} = ?" for column in changes)
        conn.execute(
            f"UPDATE job_posts SET {assignments}, updated_at = ? WHERE id = ?",
            [*changes.values(), _now(), post_id],
        )
    return get_post(post_id)


def delete_post(post_id: int) -> None:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM job_posts WHERE id = ?", (post_id,))
        if cur.rowcount == 0:
            raise JobPostNotFound(f"Job post {post_id} not found")


def fetch_post_text(post_id: int) -> dict[str, Any]:
    """Re-read the ad from its URL, or explain why the user has to paste it.

    Measured over the live URL set in October 2025, 12 of 17 domains returned
    usable text and the rest answered 403. Refusal is normal, so no failure
    path here writes the page it got into `raw_text`.
    """
    post = get_post(post_id)
    url = (post.get("url") or "").strip()
    if not url:
        raise ValueError("This job post has no URL. Paste the advertisement text instead.")
    domain = urlparse(url).netloc or url

    try:
        with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=True) as client:
            response = client.get(
                url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
    except httpx.HTTPError as exc:
        raise JobPostError(
            f"Could not reach {domain}: {exc}. Copy the advertisement and paste it instead."
        ) from exc

    if response.status_code >= 400:
        raise JobPostError(
            f"{domain} refused the request (HTTP {response.status_code}). Many job boards block "
            "automated readers. Copy the advertisement and paste it instead."
        )

    text = _clean_text(_main_content(BeautifulSoup(response.text, "html.parser")))
    if len(text) < MIN_FETCHED_CHARS:
        raise JobPostError(
            f"{domain} returned only {len(text)} characters of readable text, which is not an "
            "advertisement. The page probably needs JavaScript. Copy the advertisement and paste "
            "it instead."
        )

    logger.info("Fetched %d characters for job post %s from %s", len(text), post_id, domain)
    return update_post(post_id, {"raw_text": text, "source": "fetched"})


def extract_keywords(
    post_id: int, *, model: Optional[str] = None, refresh: bool = False
) -> dict[str, Any]:
    """Ask Claude for the ad's own terms, in three buckets.

    Any stored keywords short-circuit the call, including ones the user typed
    by hand, so re-opening a post cannot quietly overwrite their edits. An
    extraction that found nothing stores nothing and is therefore retried;
    `refresh` is the only way to overwrite a list that has content.
    """
    post = get_post(post_id)
    if post["keywords"] and not refresh:
        return post

    raw_text = (post.get("raw_text") or "").strip()
    if not raw_text:
        raise ValueError(
            "This job post has no advertisement text yet. Paste or fetch it before extracting keywords."
        )

    header = [f"Title: {post['title']}"]
    if post.get("organization"):
        header.append(f"Organization: {post['organization']}")
    if post.get("url"):
        header.append(f"URL: {post['url']}")
    prompt = "\n".join(header) + "\n\nAdvertisement:\n" + raw_text[:MAX_POST_CHARS]

    try:
        data = extract_json(
            run_claude(prompt, system=KEYWORD_SYSTEM_PROMPT, model=model, timeout=KEYWORD_TIMEOUT)
        )
    except (ClaudeCallError, ValueError) as exc:
        raise JobPostError(f"Could not extract keywords: {exc}") from exc

    keywords = _normalize_keywords(data)
    extracted_at = _now()
    with get_db() as conn:
        conn.execute(
            "UPDATE job_posts SET keywords = ?, extracted_at = ?, updated_at = ? WHERE id = ?",
            (json.dumps(keywords), extracted_at, extracted_at, post_id),
        )

    logger.info("Extracted %d keywords for job post %s", len(keywords), post_id)
    return get_post(post_id)
