"""Scraper tests that need a real HTTP round trip, served by a local http.server.

Covers the sources-status feature end to end: a scrape that hits 403/429 sets
last_status='blocked'; 500/404 sets 'error'; success clears both.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

import database
import scraper


def _seed_source(conn, url: str, **overrides) -> int:
    values = {"name": "Local Test Source", "url": url, "type": "job_board", "scrape_method": "html"}
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    conn.execute(f"INSERT INTO sources ({columns}) VALUES ({placeholders})", list(values.values()))
    return conn.execute("SELECT id FROM sources WHERE url = ?", (url,)).fetchone()["id"]


async def _run_scrape(source_row, **kwargs):
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
        return await scraper.scrape_source(client, source_row, resume_text=None, **kwargs)


def _get_source(source_id):
    with database.get_db() as conn:
        return conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()


@pytest.mark.parametrize("status", [403, 429])
def test_scrape_source_blocked_sets_status(db_path, local_server, status):
    base_url, routes = local_server
    routes.set("/jobs", status=status, body="blocked")

    with database.get_db() as conn:
        source_id = _seed_source(conn, f"{base_url}/jobs")
        source_row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()

    result = asyncio.run(_run_scrape(source_row, classify=False, verify=False))
    assert result.status == "blocked"

    row = _get_source(source_id)
    assert row["last_status"] == "blocked"
    assert row["last_error"] is not None
    assert row["last_scraped"] is not None


@pytest.mark.parametrize("status", [500, 404])
def test_scrape_source_error_status_sets_status(db_path, local_server, status):
    base_url, routes = local_server
    routes.set("/jobs", status=status, body="broken")

    with database.get_db() as conn:
        source_id = _seed_source(conn, f"{base_url}/jobs")
        source_row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()

    result = asyncio.run(_run_scrape(source_row, classify=False, verify=False))
    assert result.status == "error"

    row = _get_source(source_id)
    assert row["last_status"] == "error"
    assert row["last_error"] is not None


def test_scrape_source_success_clears_previous_blocked_status(db_path, local_server):
    base_url, routes = local_server
    routes.set(
        "/jobs",
        status=200,
        body="<html><body><main><p>" + ("A single quantum research role. " * 10) + "</p></main></body></html>",
    )

    with database.get_db() as conn:
        source_id = _seed_source(conn, f"{base_url}/jobs")
        conn.execute(
            "UPDATE sources SET last_status = 'blocked', last_error = 'HTTP 403' WHERE id = ?", (source_id,)
        )
        source_row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()

    result = asyncio.run(_run_scrape(source_row, classify=False, verify=False))
    assert result.status == "success"

    row = _get_source(source_id)
    assert row["last_status"] == "ok"
    assert row["last_error"] is None


def test_scrape_source_no_listing_content_is_an_error(db_path, local_server):
    base_url, routes = local_server
    routes.set("/jobs", status=200, body="")

    with database.get_db() as conn:
        source_id = _seed_source(conn, f"{base_url}/jobs")
        source_row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()

    result = asyncio.run(_run_scrape(source_row, classify=False, verify=False))
    assert result.status == "error"
    assert "no listing content" in result.error_message

    row = _get_source(source_id)
    assert row["last_status"] == "error"


def test_scrape_source_dead_source_page_is_an_error(db_path, local_server):
    base_url, routes = local_server
    routes.set("/jobs", status=200, body="<title>404 Page Not Found</title>")

    with database.get_db() as conn:
        source_id = _seed_source(conn, f"{base_url}/jobs")
        source_row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()

    result = asyncio.run(_run_scrape(source_row, classify=False, verify=False))
    assert result.status == "error"
    assert "source page is missing" in result.error_message


def test_scrape_source_logs_scrape_history(db_path, local_server):
    base_url, routes = local_server
    routes.set("/jobs", status=503, body="unavailable")

    with database.get_db() as conn:
        source_id = _seed_source(conn, f"{base_url}/jobs")
        source_row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()

    asyncio.run(_run_scrape(source_row, classify=False, verify=False))

    with database.get_db() as conn:
        logs = conn.execute("SELECT * FROM scrape_logs WHERE source_id = ?", (source_id,)).fetchall()
    assert len(logs) == 1
    assert logs[0]["status"] == "error"


def test_verify_listing_flags_dead_link_and_excludes_it(db_path, local_server):
    base_url, routes = local_server
    routes.set(
        "/jobs/1",
        status=200,
        body="<title>Position</title><body>" + ("filler " * 30) + "This job is no longer available.</body>",
    )

    async def _check():
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            return await scraper.verify_listing(client, f"{base_url}/jobs/1", delay=0)

    reason = asyncio.run(_check())
    assert reason is not None and "no longer available" in reason
