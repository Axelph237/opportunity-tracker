"""Scraping engine: reads the `sources` table, fetches pages, extracts listing
chunks and hands them to the classifier."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional
from urllib.parse import urljoin, urlparse, quote_plus

import httpx
from bs4 import BeautifulSoup

from classifier import classify_batch
from database import exclude_url, excluded_urls, get_db, get_setting, init_db
from resume_loader import get_resume_text

logger = logging.getLogger(__name__)

# One honest user-agent rather than a rotation of browser strings. Rotating is
# better at getting past blocks, but a tool that many people install should say
# what it is and be blockable on purpose — the requests are not a browser's.
# Paired with the per-domain delay in `_respect_rate_limit`.
USER_AGENT = (
    "OpportunityTracker/1.0 (+https://github.com/Axelph237/opportunity-tracker) "
    "python-httpx"
)

STRIP_TAGS = ("script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe")

# Containers that commonly wrap a single listing, most specific first.
CHUNK_SELECTORS = (
    "article",
    "[class*='job-card']",
    "[class*='job_card']",
    "[class*='jobCard']",
    "[class*='job-listing']",
    "[class*='opportunity']",
    "[class*='opening']",
    "[class*='position']",
    "[class*='vacancy']",
    "[class*='posting']",
    "[data-testid*='job']",
    "li",
    "tr",
    "div[class*='card']",
)

# A page can answer 200 and still be gone. These phrases, in a page's <title> or
# first heading, mean the listing no longer exists whatever the status code says.
# "404" is word-bounded: "Requisition 40412 - Quantum Engineer" is a real title.
# Nothing matches a bare "gone" either, which shows up in ordinary marketing copy.
DEAD_HEADLINE_RE = re.compile(
    r"\b404\b"
    r"|page not found"
    r"|\bnot found\b"
    r"|(?:page|position|posting|listing|job)[^.!?]{0,40}?unavailable"
    r"|page (?:does not|doesn't) exist"
    r"|no longer available",
    re.IGNORECASE,
)

# Checked against the body of an individual listing page only. A list page that
# happens to mention one closed role must not be thrown away for it.
DEAD_BODY_MARKERS = (
    "no longer accepting applications",
    "this job is no longer available",
    "this position is no longer available",
    "this posting is no longer available",
    "this opportunity is no longer available",
    "the job you are looking for",
    "this job has expired",
    "job posting has expired",
    "posting has expired",
    "position has been filled",
    "this role has been filled",
    "requisition is no longer",
    "the page you requested could not be found",
    "the page you are looking for could not be found",
    "the requested url was not found",
    "we can't find the page",
    "we cannot find the page",
    "we couldn't find that page",
    "error 404",
    "http error 404",
)

# A classifier can hallucinate a title out of a 404 page's boilerplate.
MISSING_TITLE_RE = re.compile(
    # No bare "error": "Error Correction Research Intern" is a real quantum job title.
    r"^\s*(404|403|error 404|http error|page not found|not found|access denied|"
    r"forbidden|untitled|no results|nothing found)\b",
    re.IGNORECASE,
)
MISSING_TITLE_PHRASES = ("page not found", "not found", "no longer available", "404 error")

# Blocked is not missing: the listing is there, we just cannot read it.
BLOCKED_STATUSES = frozenset({401, 402, 403, 407, 429})
MIN_LIVE_PAGE_CHARS = 120

MIN_CHUNK_CHARS = 60
MAX_CHUNK_CHARS = 4000
MIN_CHUNKS_FOR_LIST_PAGE = 3
BATCH_SIZE = 6
WHITESPACE_RE = re.compile(r"\s+")

_domain_last_request: dict[str, float] = {}
_domain_lock = asyncio.Lock()


@dataclass
class Chunk:
    url: str
    text: str


@dataclass
class SourceResult:
    source_id: int
    source_name: str
    status: str = "success"
    new_count: int = 0
    seen_count: int = 0
    chunks: int = 0
    dead_count: int = 0
    error_message: Optional[str] = None


@dataclass
class RunSummary:
    started_at: str
    finished_at: Optional[str] = None
    sources_scraped: int = 0
    new_opportunities: int = 0
    dead_links_skipped: int = 0
    errors: int = 0
    blocked: int = 0
    running: bool = False
    detail: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "sources_scraped": self.sources_scraped,
            "new_opportunities": self.new_opportunities,
            "dead_links_skipped": self.dead_links_skipped,
            "errors": self.errors,
            "blocked": self.blocked,
            "running": self.running,
            "detail": self.detail,
        }


ProgressCallback = Optional[Callable[[str], None]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _int_setting(key: str, default: int) -> int:
    try:
        return int(get_setting(key) or default)
    except (TypeError, ValueError):
        return default


def _bool_setting(key: str, default: bool) -> bool:
    value = get_setting(key)
    if value is None:
        return default
    return str(value).strip().lower() not in ("0", "false", "no", "off", "")


# ------------------------------------------------------------------------ fetching

def build_url(url: str, scrape_method: str, search_query: Optional[str]) -> str:
    """Apply a source's search_query to its base URL."""
    if not search_query:
        return url
    query = search_query.strip()
    if "{query}" in url:
        return url.replace("{query}", quote_plus(query))
    if scrape_method == "search_query":
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}q={quote_plus(query)}"
    return url


async def _respect_rate_limit(domain: str, delay: float) -> None:
    """Keep at least `delay` seconds between requests to the same domain."""
    async with _domain_lock:
        last = _domain_last_request.get(domain)
        if last is not None:
            wait = delay - (time.monotonic() - last)
            if wait > 0:
                await asyncio.sleep(wait)
        _domain_last_request[domain] = time.monotonic()


async def fetch(
    client: httpx.AsyncClient,
    url: str,
    *,
    delay: float = 2.0,
    raise_for_status: bool = True,
) -> httpx.Response:
    domain = urlparse(url).netloc
    await _respect_rate_limit(domain, delay)
    response = await client.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        follow_redirects=True,
    )
    if raise_for_status:
        response.raise_for_status()
    return response


# ----------------------------------------------------------- dead page detection

class DeadPage(Exception):
    """The fetched page exists as a URL but holds no listing any more."""


class Blocked(Exception):
    """The host refused the request outright — 403, 429 and friends.

    Distinct from every other failure: the listings are almost certainly still
    there, we are just not allowed to read them. Retrying on a schedule will not
    help, so the Sources table marks the row rather than burying it in the log.
    """

    def __init__(self, status: int, url: str) -> None:
        self.status = status
        reason = "rate limited" if status == 429 else "blocked"
        super().__init__(f"HTTP {status} — {reason} by {urlparse(url).netloc}")


def _headline(soup: BeautifulSoup) -> str:
    """The <title> plus the first couple of headings, lowercased."""
    parts: list[str] = []
    if soup.title and soup.title.string:
        parts.append(str(soup.title.string))
    for tag in soup.find_all(["h1", "h2"], limit=3):
        parts.append(tag.get_text(" ", strip=True))
    return WHITESPACE_RE.sub(" ", " ".join(parts)).strip().lower()


def _redirected_away(response: httpx.Response) -> Optional[str]:
    """True when the response landed on an ancestor of the URL we asked for.

    Only an ancestor on the same host counts: /careers/<gone> -> /careers means the
    listing is gone, while /jobs/123 -> /jobs/123/apply is a normal redirect.
    """
    # httpx rebinds response.request to the *last* hop, so the URL we actually
    # asked for lives at the head of the redirect history.
    origin = response.history[0].request if response.history else response.request
    if origin is None:
        return None
    final = urlparse(str(response.url))
    requested = urlparse(str(origin.url))
    if final.netloc.removeprefix("www.") != requested.netloc.removeprefix("www."):
        return None
    final_path = final.path.rstrip("/")
    requested_path = requested.path.rstrip("/")
    if not requested_path or final_path == requested_path:
        return None
    if final_path == "" or requested_path.startswith(final_path + "/"):
        return f"redirected up to {final.geturl()}"
    return None


def dead_page_reason(response: httpx.Response, *, deep: bool) -> Optional[str]:
    """Why this response should be treated as a missing page, or None if it is real.

    `deep` also inspects the body text and emptiness, which is only safe for an
    individual listing page — a board listing fifty roles may legitimately mention
    that one of them closed.
    """
    status = response.status_code
    if status in BLOCKED_STATUSES:
        return None  # blocked, not missing: keep whatever we already extracted
    if status >= 400:
        return f"HTTP {status}"

    # A dead listing is commonly redirected up to its section page or the home page —
    # ibm.com/careers/<gone> lands on ibm.com/careers with a 200.
    redirect = _redirected_away(response)
    if redirect:
        return redirect

    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    match = DEAD_HEADLINE_RE.search(_headline(soup))
    if match:
        return f"page heading says {match.group(0).lower()!r}"

    if not deep:
        return None

    body = _clean_text(_main_content(soup)).lower()
    if len(body) < MIN_LIVE_PAGE_CHARS:
        return "page has no readable content"
    for marker in DEAD_BODY_MARKERS:
        if marker in body[:6000]:
            return f"page says {marker!r}"
    return None


def looks_like_missing_listing(entry: dict[str, Any]) -> Optional[str]:
    """Last guard before insert: reject rows that describe an error page."""
    title = str(entry.get("title") or "").strip()
    if not title:
        return "no title"
    if MISSING_TITLE_RE.match(title):
        return f"title {title!r} reads as an error page"
    lowered = title.lower()
    for phrase in MISSING_TITLE_PHRASES:
        if phrase in lowered:
            return f"title {title!r} reads as an error page"
    organization = str(entry.get("organization") or "").strip().lower()
    if organization in ("", "unknown", "not found", "404"):
        return f"organization {organization!r} reads as an error page"
    return None


async def verify_listing(client: httpx.AsyncClient, url: str, *, delay: float) -> Optional[str]:
    """Fetch a candidate listing. Returns None when it is real, else why it is not.

    A network failure raises instead of returning a reason: we cannot prove the page
    is missing, so the listing is retried on the next run rather than blacklisted.
    """
    response = await fetch(client, url, delay=delay, raise_for_status=False)
    return dead_page_reason(response, deep=True)


async def check_listings(
    client: httpx.AsyncClient,
    chunks: list[Chunk],
    *,
    source_url: str,
    delay: float,
    say: Callable[[str], None],
) -> tuple[list[Chunk], list[tuple[str, str]]]:
    """Split candidate listings into the ones that really exist and the ones that do not.

    Dead URLs are recorded in `excluded_urls` so later runs skip them without
    paying for the request again. Listings we could not reach at all are held back
    for this run only.
    """
    live: list[Chunk] = []
    dead: list[tuple[str, str]] = []
    for chunk in chunks:
        if chunk.url == source_url:
            live.append(chunk)  # already fetched and checked above
            continue
        try:
            reason = await verify_listing(client, chunk.url, delay=delay)
        except Exception as exc:
            # Unreachable is not the same as missing — try again next run.
            say(f"  could not verify {chunk.url} ({type(exc).__name__}), holding it back")
            continue
        if reason:
            say(f"  dead link {chunk.url}: {reason}")
            exclude_url(chunk.url, "dead_link", reason)
            dead.append((chunk.url, reason))
        else:
            live.append(chunk)
    return live, dead


# ------------------------------------------------------------------ text extraction

def _clean_text(node: Any) -> str:
    return WHITESPACE_RE.sub(" ", node.get_text(" ", strip=True)).strip()


def _main_content(soup: BeautifulSoup) -> Any:
    for tag in soup.find_all(STRIP_TAGS):
        tag.decompose()
    for selector in ("main", "[role='main']", "#main", "#content", ".content", "body"):
        node = soup.select_one(selector)
        if node is not None and len(_clean_text(node)) > 100:
            return node
    return soup


def _absolute_link(element: Any, base_url: str) -> Optional[str]:
    for anchor in element.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urljoin(base_url, href)
        if urlparse(absolute).scheme in ("http", "https"):
            return absolute.split("#")[0]
    return None


def extract_chunks(html: str, base_url: str, limit: int = 12) -> list[Chunk]:
    """Split a page into individual listing chunks.

    Looks for repeated structural elements that each contain a link; falls back to
    treating the whole page as one listing when no repetition is found.
    """
    soup = BeautifulSoup(html, "html.parser")
    content = _main_content(soup)

    best: list[Chunk] = []
    for selector in CHUNK_SELECTORS:
        try:
            elements = content.select(selector)
        except Exception:
            continue

        found: list[Chunk] = []
        seen_urls: set[str] = set()
        for element in elements:
            text = _clean_text(element)
            if not (MIN_CHUNK_CHARS <= len(text) <= MAX_CHUNK_CHARS):
                continue
            url = _absolute_link(element, base_url)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            found.append(Chunk(url=url, text=text))

        if len(found) >= MIN_CHUNKS_FOR_LIST_PAGE:
            best = found
            break
        if len(found) > len(best):
            best = found

    if len(best) < MIN_CHUNKS_FOR_LIST_PAGE:
        page_text = _clean_text(content)[:MAX_CHUNK_CHARS]
        if page_text:
            return [Chunk(url=base_url, text=page_text)]
        return []

    return best[:limit]


def extract_json_chunks(payload: Any, base_url: str, limit: int = 12) -> list[Chunk]:
    """Turn an API response into listing chunks."""
    records: list[Any] = []
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        for key in ("jobs", "results", "data", "items", "postings", "listings", "openings"):
            value = payload.get(key)
            if isinstance(value, list):
                records = value
                break
        else:
            records = [payload]

    chunks: list[Chunk] = []
    seen: set[str] = set()
    for record in records[: limit * 2]:
        if not isinstance(record, (dict, list)):
            continue
        text = WHITESPACE_RE.sub(" ", json.dumps(record, ensure_ascii=False))[:MAX_CHUNK_CHARS]
        url = base_url
        if isinstance(record, dict):
            for key in ("url", "absolute_url", "apply_url", "link", "href", "jobUrl"):
                value = record.get(key)
                if isinstance(value, str) and value.strip():
                    url = urljoin(base_url, value.strip())
                    break
            else:
                identifier = record.get("id") or record.get("slug")
                if identifier is not None:
                    url = f"{base_url}#{identifier}"
        if url in seen:
            continue
        seen.add(url)
        chunks.append(Chunk(url=url, text=text))
        if len(chunks) >= limit:
            break
    return chunks


# --------------------------------------------------------------------- persistence

def existing_urls(conn: sqlite3.Connection, urls: Iterable[str]) -> set[str]:
    urls = list(urls)
    if not urls:
        return set()
    found: set[str] = set()
    for start in range(0, len(urls), 400):
        batch = urls[start : start + 400]
        placeholders = ",".join("?" * len(batch))
        rows = conn.execute(f"SELECT url FROM opportunities WHERE url IN ({placeholders})", batch).fetchall()
        found.update(row["url"] for row in rows)
    return found


def touch_last_seen(conn: sqlite3.Connection, urls: Iterable[str]) -> None:
    timestamp = _now()
    conn.executemany(
        "UPDATE opportunities SET last_seen = ?, is_active = 1 WHERE url = ?",
        [(timestamp, url) for url in urls],
    )


def insert_opportunity(conn: sqlite3.Connection, result: dict[str, Any], source_id: Optional[int]) -> bool:
    """Insert one classified listing. Returns True when a new row was created."""
    cur = conn.execute(
        """INSERT OR IGNORE INTO opportunities (
               title, organization, type, location, remote, url, description, deadline,
               source_id, relevance_score, relevance_summary, skill_matches,
               experience_level, strong_match, tags, is_active, last_seen
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
        (
            result["title"],
            result["organization"],
            result["type"],
            result.get("location"),
            int(bool(result.get("remote"))),
            result["url"],
            result.get("description"),
            result.get("deadline"),
            source_id,
            result.get("relevance_score"),
            result.get("relevance_summary"),
            json.dumps(result.get("skill_matches") or []),
            result.get("experience_level"),
            int(bool(result.get("strong_match"))),
            json.dumps(result.get("tags") or []),
            _now(),
        ),
    )
    return cur.rowcount > 0


def log_scrape(conn: sqlite3.Connection, source_id: Optional[int], status: str, new_count: int, error: Optional[str]) -> None:
    conn.execute(
        "INSERT INTO scrape_logs (source_id, timestamp, status, new_count, error_message) VALUES (?, ?, ?, ?, ?)",
        (source_id, _now(), status, new_count, (error or None) and str(error)[:800]),
    )


# ------------------------------------------------------------------------ scraping

def get_sources(source_ids: Optional[list[int]] = None, active_only: bool = True) -> list[sqlite3.Row]:
    query = "SELECT * FROM sources WHERE pending_approval = 0"
    params: list[Any] = []
    if active_only:
        query += " AND active = 1"
    if source_ids:
        query += f" AND id IN ({','.join('?' * len(source_ids))})"
        params.extend(source_ids)
    query += " ORDER BY id"
    with get_db() as conn:
        return conn.execute(query, params).fetchall()


async def scrape_source(
    client: httpx.AsyncClient,
    source: sqlite3.Row,
    resume_text: Optional[str],
    *,
    classify: bool = True,
    verify: bool = True,
    progress: ProgressCallback = None,
) -> SourceResult:
    """Scrape a single source end to end and persist any new opportunities."""
    result = SourceResult(source_id=source["id"], source_name=source["name"])
    say = progress or (lambda message: None)
    max_chunks = _int_setting("max_chunks_per_source", 12)
    delay = float(_int_setting("domain_delay_seconds", 2))
    url = build_url(source["url"], source["scrape_method"], source["search_query"])

    try:
        say(f"[{source['name']}] fetching {url}")
        try:
            response = await fetch(client, url, delay=delay)
        except httpx.HTTPStatusError as exc:
            # A refusal is worth naming; every other status stays a plain error.
            if exc.response.status_code in BLOCKED_STATUSES:
                raise Blocked(exc.response.status_code, url) from exc
            raise

        page_gone = dead_page_reason(response, deep=False)
        if page_gone:
            raise DeadPage(f"source page is missing: {page_gone}")

        content_type = response.headers.get("content-type", "")
        if source["scrape_method"] == "api" or "application/json" in content_type:
            try:
                chunks = extract_json_chunks(response.json(), url, limit=max_chunks)
            except ValueError:
                chunks = extract_chunks(response.text, url, limit=max_chunks)
        else:
            chunks = extract_chunks(response.text, url, limit=max_chunks)

        result.chunks = len(chunks)
        say(f"[{source['name']}] found {len(chunks)} candidate listing(s)")
        if not chunks:
            raise ValueError("no listing content could be extracted from the page")

        # Deduplicate against the database before spending any Claude calls.
        with get_db() as conn:
            known = existing_urls(conn, [chunk.url for chunk in chunks])
            if known:
                touch_last_seen(conn, known)
            skip = excluded_urls(conn)
        fresh = [chunk for chunk in chunks if chunk.url not in known and chunk.url not in skip]
        dropped = sum(1 for chunk in chunks if chunk.url not in known and chunk.url in skip)
        result.seen_count = len(known)
        if dropped:
            say(f"[{source['name']}] skipped {dropped} previously deleted or dead link(s)")
        if known:
            say(f"[{source['name']}] {len(known)} already known, {len(fresh)} new to classify")

        if fresh and verify:
            fresh, dead = await check_listings(client, fresh, source_url=url, delay=delay, say=say)
            result.dead_count = len(dead)
            if dead:
                say(f"[{source['name']}] dropped {len(dead)} missing page(s) before classifying")

        if not fresh:
            with get_db() as conn:
                conn.execute(
                    "UPDATE sources SET last_scraped = ?, last_result_count = ?, "
                    "last_status = 'ok', last_error = NULL WHERE id = ?",
                    (_now(), 0, source["id"]),
                )
                log_scrape(conn, source["id"], "success", 0, None)
            return result

        if not classify:
            say(f"[{source['name']}] classification disabled, skipping {len(fresh)} listing(s)")
            with get_db() as conn:
                conn.execute(
                    "UPDATE sources SET last_scraped = ?, last_status = 'ok', last_error = NULL WHERE id = ?",
                    (_now(), source["id"]),
                )
            return result

        classified: list[dict[str, Any]] = []
        for start in range(0, len(fresh), BATCH_SIZE):
            batch = fresh[start : start + BATCH_SIZE]
            say(f"[{source['name']}] classifying {start + 1}-{start + len(batch)} of {len(fresh)}")
            classified.extend(
                await asyncio.to_thread(
                    classify_batch,
                    [{"url": chunk.url, "text": chunk.text} for chunk in batch],
                    resume_text,
                    source_name=source["name"],
                )
            )

        with get_db() as conn:
            for entry in classified:
                if entry.get("relevance_score", 0) <= 0 and entry.get("error"):
                    continue  # classification failed; don't store a junk row
                missing = looks_like_missing_listing(entry)
                if missing:
                    # The fetch looked fine but the text was an error page after all.
                    say(f"[{source['name']}] discarded {entry.get('url')}: {missing}")
                    exclude_url(str(entry.get("url")), "dead_link", missing)
                    result.dead_count += 1
                    continue
                if insert_opportunity(conn, entry, source["id"]):
                    result.new_count += 1
            conn.execute(
                "UPDATE sources SET last_scraped = ?, last_result_count = ?, "
                "last_status = 'ok', last_error = NULL WHERE id = ?",
                (_now(), result.new_count, source["id"]),
            )
            log_scrape(conn, source["id"], "success", result.new_count, None)

        say(f"[{source['name']}] done — {result.new_count} new opportunit(ies)")

    except Exception as exc:
        blocked = isinstance(exc, Blocked)
        # A Blocked message already reads as a sentence; anything else needs its
        # exception type to be intelligible.
        message = str(exc) if blocked else f"{type(exc).__name__}: {exc}"
        result.status = "blocked" if blocked else "error"
        result.error_message = message
        logger.warning("Scrape failed for %s: %s", source["name"], message)
        say(f"[{source['name']}] {'BLOCKED' if blocked else 'ERROR'} {message}")
        try:
            with get_db() as conn:
                conn.execute(
                    "UPDATE sources SET last_scraped = ?, last_status = ?, last_error = ? WHERE id = ?",
                    (_now(), "blocked" if blocked else "error", message[:400], source["id"]),
                )
                log_scrape(conn, source["id"], "error", 0, message)
        except Exception:
            logger.exception("Could not record scrape error for source %s", source["id"])

    return result


async def scrape_all(
    source_ids: Optional[list[int]] = None,
    *,
    classify: bool = True,
    verify: Optional[bool] = None,
    progress: ProgressCallback = None,
) -> RunSummary:
    """Scrape every active source (or the given subset) sequentially."""
    summary = RunSummary(started_at=_now(), running=True)
    say = progress or (lambda message: None)
    sources = get_sources(source_ids)
    if not sources:
        say("No active sources to scrape.")
        summary.running = False
        summary.finished_at = _now()
        return summary

    resume_text = get_resume_text()
    if not resume_text:
        say("WARNING: no resume loaded — relevance scores will be generic.")

    if verify is None:
        verify = _bool_setting("verify_listing_urls", True)
    timeout = httpx.Timeout(float(_int_setting("request_timeout_seconds", 15)))
    say(f"Starting scrape of {len(sources)} source(s)" + ("" if verify else " (listing verification off)"))

    async with httpx.AsyncClient(timeout=timeout) as client:
        for source in sources:
            result = await scrape_source(
                client, source, resume_text, classify=classify, verify=verify, progress=progress
            )
            summary.sources_scraped += 1
            summary.new_opportunities += result.new_count
            summary.dead_links_skipped += result.dead_count
            if result.status in ("error", "blocked"):
                summary.errors += 1
            if result.status == "blocked":
                summary.blocked += 1
            summary.detail.append(
                {
                    "source_id": result.source_id,
                    "source_name": result.source_name,
                    "status": result.status,
                    "chunks": result.chunks,
                    "already_known": result.seen_count,
                    "dead_count": result.dead_count,
                    "new_count": result.new_count,
                    "error_message": result.error_message,
                }
            )

    summary.running = False
    summary.finished_at = _now()
    say(
        f"Scrape finished: {summary.sources_scraped} source(s), "
        f"{summary.new_opportunities} new opportunit(ies), "
        f"{summary.dead_links_skipped} dead link(s) skipped, {summary.errors} error(s)"
        + (f" of which {summary.blocked} blocked" if summary.blocked else "")
    )
    return summary


# ------------------------------------------------------------------ housekeeping

async def prune_dead_opportunities(
    *,
    limit: Optional[int] = None,
    dry_run: bool = False,
    progress: ProgressCallback = None,
) -> dict[str, Any]:
    """Re-check stored opportunities and drop the ones whose page has gone.

    Cleans up rows added before URL verification existed. Deleted URLs are recorded
    so a later scrape does not simply put them back.
    """
    say = progress or (lambda message: None)
    with get_db() as conn:
        query = "SELECT id, url, title FROM opportunities ORDER BY id"
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = conn.execute(query).fetchall()

    delay = float(_int_setting("domain_delay_seconds", 2))
    timeout = httpx.Timeout(float(_int_setting("request_timeout_seconds", 15)))
    removed: list[dict[str, str]] = []
    unreachable = 0

    say(f"Checking {len(rows)} stored opportunit(ies)")
    async with httpx.AsyncClient(timeout=timeout) as client:
        for row in rows:
            try:
                reason = await verify_listing(client, row["url"], delay=delay)
            except Exception as exc:
                unreachable += 1
                say(f"  ? {row['url']} — could not check ({type(exc).__name__})")
                continue
            if not reason:
                continue
            say(f"  ✗ {row['title']} — {reason}")
            removed.append({"url": row["url"], "title": row["title"], "reason": reason})
            if dry_run:
                continue
            exclude_url(row["url"], "dead_link", reason)
            with get_db() as conn:
                conn.execute("DELETE FROM opportunities WHERE id = ?", (row["id"],))

    say(
        f"{'Would remove' if dry_run else 'Removed'} {len(removed)} dead listing(s); "
        f"{unreachable} could not be checked"
    )
    return {"checked": len(rows), "removed": removed, "unreachable": unreachable, "dry_run": dry_run}


# ----------------------------------------------------------------------------- CLI

def main() -> None:
    parser = argparse.ArgumentParser(description="Run the opportunity scraper.")
    parser.add_argument("--source-id", type=int, action="append", dest="source_ids", help="Scrape only this source (repeatable)")
    parser.add_argument("--list", action="store_true", help="List sources and exit")
    parser.add_argument("--no-classify", action="store_true", help="Fetch and chunk only, skip Claude calls")
    parser.add_argument("--no-verify", action="store_true", help="Skip the 404 check on each candidate listing URL")
    parser.add_argument("--prune-dead", action="store_true", help="Re-check stored opportunities and delete dead pages")
    parser.add_argument("--prune-limit", type=int, help="Only check the first N stored opportunities")
    parser.add_argument("--dry-run", action="store_true", help="With --prune-dead, report without deleting")
    parser.add_argument("--json", action="store_true", help="Print the run summary as JSON")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    init_db()

    if args.list:
        for source in get_sources(active_only=False):
            state = "active" if source["active"] else "paused"
            print(f"{source['id']:>3}  {state:<7} {source['type']:<18} {source['name']}  {source['url']}")
        return

    progress = None if args.quiet else (lambda message: print(message, flush=True))

    if args.prune_dead:
        report = asyncio.run(
            prune_dead_opportunities(limit=args.prune_limit, dry_run=args.dry_run, progress=progress)
        )
        if args.json:
            print(json.dumps(report, indent=2))
        return

    summary = asyncio.run(
        scrape_all(
            args.source_ids,
            classify=not args.no_classify,
            verify=False if args.no_verify else None,
            progress=progress,
        )
    )
    if args.json:
        print(json.dumps(summary.to_dict(), indent=2))


if __name__ == "__main__":
    main()
