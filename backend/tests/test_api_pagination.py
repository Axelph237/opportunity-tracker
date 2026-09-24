"""Paging the listings and sources tables, and the row count the pager needs."""

from __future__ import annotations

import database


def make_opportunities(count, **overrides):
    with database.get_db() as conn:
        for index in range(count):
            conn.execute(
                """INSERT INTO opportunities (title, organization, type, url, relevance_score)
                   VALUES (?, 'ACME', 'job', ?, ?)""",
                (f"Role {index:03d}", f"https://example.com/{index}", 10 - index * 0.01),
            )


def make_sources(count):
    with database.get_db() as conn:
        for index in range(count):
            conn.execute(
                """INSERT INTO sources (name, url, type) VALUES (?, ?, 'job_board')""",
                (f"Board {index:03d}", f"https://board-{index}.example.com"),
            )


# ------------------------------------------------------------- opportunities

def test_a_page_is_limited_to_what_was_asked_for(app_client):
    make_opportunities(60)
    rows = app_client.get("/api/opportunities?limit=25&offset=0").json()
    assert len(rows) == 25


def test_the_second_page_continues_where_the_first_stopped(app_client):
    make_opportunities(60)
    first = app_client.get("/api/opportunities?limit=25&offset=0").json()
    second = app_client.get("/api/opportunities?limit=25&offset=25").json()
    assert {row["id"] for row in first}.isdisjoint({row["id"] for row in second})
    assert len(second) == 25


def test_the_last_page_is_short_rather_than_padded(app_client):
    make_opportunities(60)
    assert len(app_client.get("/api/opportunities?limit=25&offset=50").json()) == 10


def test_a_page_past_the_end_is_empty_not_an_error(app_client):
    make_opportunities(10)
    response = app_client.get("/api/opportunities?limit=25&offset=500")
    assert response.status_code == 200
    assert response.json() == []


def test_the_total_counts_every_match_not_just_the_page(app_client):
    """The pager cannot say "page 1 of 3" from the length of page 1."""
    make_opportunities(60)
    response = app_client.get("/api/opportunities?limit=25&offset=0")
    assert response.headers["x-total-count"] == "60"
    assert len(response.json()) == 25


def test_the_total_respects_the_filters(app_client):
    make_opportunities(30)
    with database.get_db() as conn:
        conn.execute("UPDATE opportunities SET type = 'internship' WHERE id % 2 = 0")
    response = app_client.get("/api/opportunities?type=internship&limit=25")
    assert response.headers["x-total-count"] == "15"


def test_the_total_does_not_count_inactive_listings_by_default(app_client):
    make_opportunities(10)
    with database.get_db() as conn:
        conn.execute("UPDATE opportunities SET is_active = 0 WHERE id % 2 = 0")
    assert app_client.get("/api/opportunities").headers["x-total-count"] == "5"


def test_paging_does_not_skip_or_repeat_a_row_across_the_whole_table(app_client):
    """The ordering has to be total, or a row can sit on two pages while
    another sits on none."""
    make_opportunities(57)
    seen = []
    for offset in range(0, 75, 25):
        seen.extend(row["id"] for row in app_client.get(
            f"/api/opportunities?limit=25&offset={offset}"
        ).json())
    assert len(seen) == 57
    assert len(set(seen)) == 57


def test_paging_is_stable_under_a_sort_with_ties(app_client):
    """Every score identical, so only the id tiebreak keeps the pages apart."""
    make_opportunities(40)
    with database.get_db() as conn:
        conn.execute("UPDATE opportunities SET relevance_score = 5.0")
    seen = []
    for offset in (0, 20):
        seen.extend(row["id"] for row in app_client.get(
            f"/api/opportunities?sort=relevance_score&limit=20&offset={offset}"
        ).json())
    assert len(set(seen)) == 40


# ------------------------------------------------------------------- sources

def test_sources_page_and_report_their_total(app_client):
    # 20 starter sources are seeded on first run.
    make_sources(40)
    response = app_client.get("/api/sources?limit=25&offset=0")
    assert len(response.json()) == 25
    assert int(response.headers["x-total-count"]) == 60


def test_the_second_page_of_sources_is_different(app_client):
    make_sources(40)
    first = app_client.get("/api/sources?limit=25&offset=0").json()
    second = app_client.get("/api/sources?limit=25&offset=25").json()
    assert {row["id"] for row in first}.isdisjoint({row["id"] for row in second})


def test_the_sources_total_respects_a_filter(app_client):
    make_sources(10)
    with database.get_db() as conn:
        conn.execute("UPDATE sources SET active = 0")
        conn.execute("UPDATE sources SET active = 1 WHERE id % 3 = 0")
    total = int(app_client.get("/api/sources?active=true").headers["x-total-count"])
    assert total == len(app_client.get("/api/sources?active=true&limit=1000").json())
