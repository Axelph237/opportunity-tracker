"""Site icons for the listings and sources tables, fetched once and cached.

Keyed by domain rather than by row. Twenty IBM listings share one icon, so a
per-row copy would mean twenty downloads and twenty blobs of the same bytes;
the table still shows an icon per entry, it just resolves through the domain.

Taken from the site itself rather than one of the public favicon services. The
app's promise is that it runs on your own machine and your resume never leaves
it, and routing the name of every company you are looking at through a third
party would quietly undo a good part of that. The scraper already visits these
pages, so nothing new is being contacted.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

from database import get_db

logger = logging.getLogger(__name__)

TIMEOUT = 8.0
MAX_BYTES = 250_000
# A site that had no icon today probably still has none tomorrow, but a
# redesign should not be invisible forever.
RETRY_MISSING_AFTER_DAYS = 14

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

# Hostnames only: letters, digits, dots and hyphens. Anything else is not a
# domain we put in the database, so it is not one worth resolving.
_DOMAIN_RE = re.compile(r"^[a-z0-9.-]{1,253}$")
_LINK_RE = re.compile(
    r"""<link\s[^>]*rel\s*=\s*["']?[^"'>]*\bicon\b[^"'>]*["']?[^>]*>""",
    re.IGNORECASE,
)
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)

IMAGE_TYPES = ("image/", "application/octet-stream")

# A fresh page of 25 rows can ask for 25 unknown domains at once, and each of
# those is a blocking HTTP call on a threadpool worker that the rest of the API
# also draws from. Only a few run at a time; the rest fall back to the generic
# glyph and are picked up on a later visit, which is a far better failure than
# the whole app going unresponsive while it waits on someone's slow CDN.
_FETCH_SLOTS = threading.Semaphore(4)


def domain_of(url: Optional[str]) -> Optional[str]:
    """The bare hostname of a URL, lowercased and without `www.`."""
    if not url:
        return None
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return None
    if not host:
        return None
    host = host.removeprefix("www.")
    return host if _DOMAIN_RE.match(host) else None


def known_domains(conn: Optional[sqlite3.Connection] = None) -> set[str]:
    """Domains the app already tracks.

    The fetch endpoint takes a domain from the client, so without this it would
    be an open proxy: ask it for `192.168.1.1` and the server makes the
    request. Only sites already in the user's own data are resolvable.
    """
    query = "SELECT url FROM opportunities UNION SELECT url FROM sources"
    rows = conn.execute(query).fetchall() if conn else None
    if rows is None:
        with get_db() as own:
            rows = own.execute(query).fetchall()
    return {domain for domain in (domain_of(row["url"]) for row in rows) if domain}


def lookup(domain: str) -> Optional[dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM favicons WHERE domain = ?", (domain,)).fetchone()
    return dict(row) if row else None


def _store(domain: str, data: Optional[bytes], content_type: Optional[str]) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO favicons (domain, data, content_type, fetched_at, ok)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(domain) DO UPDATE SET
                   data = excluded.data,
                   content_type = excluded.content_type,
                   fetched_at = excluded.fetched_at,
                   ok = excluded.ok""",
            (
                domain,
                data,
                content_type,
                datetime.now(tz=timezone.utc).isoformat(),
                int(bool(data)),
            ),
        )


def _is_stale(row: dict) -> bool:
    """Only a recorded miss is ever refetched; a stored icon is kept."""
    if row["ok"]:
        return False
    try:
        fetched = datetime.fromisoformat(row["fetched_at"])
    except (TypeError, ValueError):
        return True
    age = datetime.now(tz=timezone.utc) - fetched
    return age.days >= RETRY_MISSING_AFTER_DAYS


def _icon_urls(domain: str, html: str) -> list[str]:
    """Candidate icon URLs, the page's own declarations first."""
    base = f"https://{domain}/"
    found = []
    for tag in _LINK_RE.findall(html or ""):
        href = _HREF_RE.search(tag)
        if href:
            found.append(urljoin(base, href.group(1)))
    # The conventional location, which most sites have even when they declare
    # nothing in the markup.
    found.append(urljoin(base, "/favicon.ico"))
    seen, unique = set(), []
    for url in found:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique[:4]


def fetch(domain: str) -> Optional[tuple[bytes, str]]:
    """Download a site's icon. Returns None when it has none we can use."""
    headers = {"User-Agent": USER_AGENT}
    try:
        with httpx.Client(
            timeout=TIMEOUT, follow_redirects=True, headers=headers
        ) as client:
            html = ""
            try:
                page = client.get(f"https://{domain}/")
                if page.status_code < 400 and "html" in page.headers.get("content-type", ""):
                    html = page.text[:200_000]
            except httpx.HTTPError:
                # No landing page is fine; /favicon.ico may still be there.
                pass

            for url in _icon_urls(domain, html):
                try:
                    response = client.get(url)
                except httpx.HTTPError:
                    continue
                if response.status_code >= 400 or not response.content:
                    continue
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                if content_type and not content_type.startswith(IMAGE_TYPES):
                    continue
                if len(response.content) > MAX_BYTES:
                    continue
                return response.content, content_type or "image/x-icon"
    except Exception as exc:  # a malformed host, a TLS failure, anything
        logger.debug("Favicon fetch failed for %s: %s", domain, exc)
    return None


def get_or_fetch(domain: str) -> Optional[dict]:
    """The cached icon, downloading it the first time it is asked for.

    A miss is cached too, so a site without an icon is not re-requested on
    every page of the table.
    """
    row = lookup(domain)
    if row and not _is_stale(row):
        return row if row["ok"] else None

    if not _FETCH_SLOTS.acquire(blocking=False):
        # Deliberately not cached as a miss: nothing was learned about the
        # site, only that we were busy. The next page load tries again.
        logger.debug("Skipped favicon fetch for %s: too many in flight", domain)
        return None
    try:
        result = fetch(domain)
    finally:
        _FETCH_SLOTS.release()

    if result is None:
        _store(domain, None, None)
        return None
    data, content_type = result
    _store(domain, data, content_type)
    logger.info("Cached favicon for %s (%d bytes)", domain, len(data))
    return lookup(domain)
