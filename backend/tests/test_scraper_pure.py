"""Pure-function scraper logic: no network, no local server.

httpx.Response objects can be constructed directly, so `dead_page_reason` and
friends are exercised against crafted responses instead of a live fetch.
"""

from __future__ import annotations

import httpx
import pytest

import scraper


def _response(url: str, status: int = 200, text: str = "", history: list | None = None,
               final_url: str | None = None, content_type: str = "text/html") -> httpx.Response:
    request = httpx.Request("GET", final_url or url)
    return httpx.Response(
        status,
        request=request,
        text=text,
        history=history or [],
        headers={"content-type": content_type},
    )


# --------------------------------------------------------------- dead_page_reason

def test_dead_page_reason_none_for_healthy_page():
    resp = _response("https://example.com/jobs/1", 200, "<title>Quantum Intern</title>")
    assert scraper.dead_page_reason(resp, deep=False) is None


def test_dead_page_reason_blocked_status_returns_none():
    """Blocked is not missing: the caller distinguishes it via the exception path."""
    resp = _response("https://example.com/jobs/1", 403, "<title>Forbidden</title>")
    assert scraper.dead_page_reason(resp, deep=False) is None


def test_dead_page_reason_generic_http_error():
    resp = _response("https://example.com/jobs/1", 500, "<title>Server Error</title>")
    assert scraper.dead_page_reason(resp, deep=False) == "HTTP 500"


def test_dead_page_reason_title_says_not_found():
    resp = _response("https://example.com/jobs/1", 200, "<title>404 - Page Not Found</title>")
    reason = scraper.dead_page_reason(resp, deep=False)
    assert reason is not None and "404" in reason


def test_dead_page_reason_requisition_number_is_not_a_false_positive():
    """A real job with '404' in its requisition number must not look dead."""
    resp = _response(
        "https://example.com/jobs/1", 200,
        "<title>Requisition 40412 - Quantum Engineer</title>",
    )
    assert scraper.dead_page_reason(resp, deep=False) is None


def test_dead_page_reason_json_content_type_skips_html_checks():
    resp = _response("https://example.com/api/jobs/1", 200, "{}", content_type="application/json")
    assert scraper.dead_page_reason(resp, deep=False) is None


def test_dead_page_reason_redirected_up_to_section_page():
    resp = _response(
        "https://example.com/careers/gone", 200, "<title>Careers</title>",
        history=[_response("https://example.com/careers/gone", 301)],
        final_url="https://example.com/careers",
    )
    reason = scraper.dead_page_reason(resp, deep=False)
    assert reason is not None and "redirected" in reason


def test_dead_page_reason_normal_redirect_within_listing_is_not_dead():
    """/jobs/123 -> /jobs/123/apply is a normal redirect, not a removal."""
    resp = _response(
        "https://example.com/jobs/123", 200, "<title>Quantum Intern</title>",
        history=[_response("https://example.com/jobs/123", 301)],
        final_url="https://example.com/jobs/123/apply",
    )
    assert scraper.dead_page_reason(resp, deep=False) is None


def test_dead_page_reason_shallow_ignores_body_markers():
    """deep=False must not inspect body text (only safe for a single listing)."""
    resp = _response(
        "https://example.com/jobs", 200,
        "<title>Careers</title><body>This job is no longer available, but others are.</body>",
    )
    assert scraper.dead_page_reason(resp, deep=False) is None


def test_dead_page_reason_deep_catches_body_marker():
    resp = _response(
        "https://example.com/jobs/1", 200,
        "<title>Quantum Engineer</title><body>" + ("filler text " * 20) +
        "This job is no longer available. Please check back later.</body>",
    )
    reason = scraper.dead_page_reason(resp, deep=True)
    assert reason is not None and "no longer available" in reason


def test_dead_page_reason_deep_empty_body():
    resp = _response("https://example.com/jobs/1", 200, "<title>x</title><body></body>")
    reason = scraper.dead_page_reason(resp, deep=True)
    assert reason == "page has no readable content"


# --------------------------------------------------------- looks_like_missing_listing

def test_looks_like_missing_listing_no_title():
    assert scraper.looks_like_missing_listing({"title": "", "organization": "Acme"}) == "no title"


def test_looks_like_missing_listing_error_title():
    reason = scraper.looks_like_missing_listing({"title": "404 Not Found", "organization": "Acme"})
    assert reason is not None


def test_looks_like_missing_listing_real_title_with_error_number():
    """'Error Correction Research Intern' must not be flagged for containing 'error'."""
    reason = scraper.looks_like_missing_listing(
        {"title": "Error Correction Research Intern", "organization": "IonQ"}
    )
    assert reason is None


def test_looks_like_missing_listing_unknown_organization():
    reason = scraper.looks_like_missing_listing({"title": "Quantum Intern", "organization": "unknown"})
    assert reason is not None and "organization" in reason


def test_looks_like_missing_listing_real_listing_passes():
    reason = scraper.looks_like_missing_listing({"title": "Quantum Intern", "organization": "IonQ"})
    assert reason is None


# ------------------------------------------------------------------------ build_url

def test_build_url_no_search_query_returns_original():
    assert scraper.build_url("https://example.com/jobs", "html", None) == "https://example.com/jobs"


def test_build_url_template_placeholder():
    url = scraper.build_url("https://example.com/jobs?q={query}", "html", "quantum computing")
    assert url == "https://example.com/jobs?q=quantum+computing"


def test_build_url_search_query_method_appends_q_param_no_existing_query():
    url = scraper.build_url("https://example.com/jobs", "search_query", "quantum computing")
    assert url == "https://example.com/jobs?q=quantum+computing"


def test_build_url_search_query_method_appends_q_param_existing_query():
    url = scraper.build_url("https://example.com/jobs?page=2", "search_query", "quantum computing")
    assert url == "https://example.com/jobs?page=2&q=quantum+computing"


def test_build_url_html_method_without_placeholder_is_unchanged():
    url = scraper.build_url("https://example.com/jobs", "html", "quantum computing")
    assert url == "https://example.com/jobs"


# --------------------------------------------------------------------- extract_chunks

LISTING_PAGE_HTML = """
<html><body>
<div id="content">
<article><a href="/jobs/1">Job One</a><p>{filler}</p></article>
<article><a href="/jobs/2">Job Two</a><p>{filler}</p></article>
<article><a href="/jobs/3">Job Three</a><p>{filler}</p></article>
</div>
</body></html>
""".replace("{filler}", "Quantum computing research role requiring Python and linear algebra. " * 2)


def test_extract_chunks_finds_repeated_articles():
    chunks = scraper.extract_chunks(LISTING_PAGE_HTML, "https://example.com/jobs")
    assert len(chunks) == 3
    urls = {c.url for c in chunks}
    assert urls == {
        "https://example.com/jobs/1",
        "https://example.com/jobs/2",
        "https://example.com/jobs/3",
    }


def test_extract_chunks_deduplicates_same_url():
    html = """
    <html><body>
    <article><a href="/jobs/1">A</a><p>{filler}</p></article>
    <article><a href="/jobs/1">A again</a><p>{filler}</p></article>
    <article><a href="/jobs/2">B</a><p>{filler}</p></article>
    <article><a href="/jobs/3">C</a><p>{filler}</p></article>
    </body></html>
    """.replace("{filler}", "Quantum computing research role. " * 3)
    chunks = scraper.extract_chunks(html, "https://example.com/jobs")
    urls = [c.url for c in chunks]
    assert urls.count("https://example.com/jobs/1") == 1


def test_extract_chunks_respects_limit():
    articles = "".join(
        f'<article><a href="/jobs/{i}">Job {i}</a><p>{"Quantum role text. " * 5}</p></article>'
        for i in range(10)
    )
    html = f"<html><body>{articles}</body></html>"
    chunks = scraper.extract_chunks(html, "https://example.com/jobs", limit=4)
    assert len(chunks) == 4


def test_extract_chunks_falls_back_to_whole_page_when_no_repetition():
    html = "<html><body><main><p>" + ("Just one long page of text about a single role. " * 5) + "</p></main></body></html>"
    chunks = scraper.extract_chunks(html, "https://example.com/jobs")
    assert len(chunks) == 1
    assert chunks[0].url == "https://example.com/jobs"


def test_extract_chunks_empty_page_returns_nothing():
    chunks = scraper.extract_chunks("<html><body></body></html>", "https://example.com/jobs")
    assert chunks == []


def test_extract_chunks_ignores_chunk_without_link():
    html = """
    <html><body>
    <article><a href="/jobs/1">A</a><p>{filler}</p></article>
    <article><p>No link here at all, just filler text. {filler}</p></article>
    <article><a href="/jobs/2">B</a><p>{filler}</p></article>
    <article><a href="/jobs/3">C</a><p>{filler}</p></article>
    </body></html>
    """.replace("{filler}", "Quantum computing research role. " * 3)
    chunks = scraper.extract_chunks(html, "https://example.com/jobs")
    assert all(c.url != "https://example.com/jobs" or len(chunks) == 1 for c in chunks)
    assert len(chunks) == 3


# ------------------------------------------------------------------ extract_json_chunks

def test_extract_json_chunks_list_payload():
    payload = [
        {"id": 1, "title": "Job One", "url": "https://example.com/jobs/1"},
        {"id": 2, "title": "Job Two", "url": "https://example.com/jobs/2"},
    ]
    chunks = scraper.extract_json_chunks(payload, "https://example.com/jobs")
    assert len(chunks) == 2
    assert chunks[0].url == "https://example.com/jobs/1"


def test_extract_json_chunks_dict_with_known_key():
    payload = {"jobs": [{"id": 1, "absolute_url": "https://example.com/jobs/1"}]}
    chunks = scraper.extract_json_chunks(payload, "https://example.com/jobs")
    assert len(chunks) == 1
    assert chunks[0].url == "https://example.com/jobs/1"


def test_extract_json_chunks_dict_without_known_key_treats_as_single_record():
    payload = {"title": "Single job posting"}
    chunks = scraper.extract_json_chunks(payload, "https://example.com/jobs")
    assert len(chunks) == 1
    assert chunks[0].url == "https://example.com/jobs"


def test_extract_json_chunks_uses_id_fragment_when_no_url_field():
    payload = [{"id": "abc123", "title": "Job"}]
    chunks = scraper.extract_json_chunks(payload, "https://example.com/jobs")
    assert chunks[0].url == "https://example.com/jobs#abc123"


# ------------------------------------------------------------------------- Blocked

def test_blocked_exception_message_for_rate_limit():
    exc = scraper.Blocked(429, "https://example.com/jobs")
    assert "rate limited" in str(exc)
    assert exc.status == 429


def test_blocked_exception_message_for_forbidden():
    exc = scraper.Blocked(403, "https://example.com/jobs")
    assert "blocked by example.com" in str(exc)
