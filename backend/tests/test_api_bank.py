"""The experience-bank and draft tables, and the API surface reserved for them."""

from __future__ import annotations

import sqlite3

import pytest

import database

NEW_TABLES = ("bank_entries", "bank_bullets", "job_posts", "resume_drafts", "draft_proposals")

# Every endpoint the builder owns, with a body valid enough to reach the
# handler: a request rejected during validation would answer 422 and prove
# nothing about whether the route is registered.
STUBBED_ROUTES = [
    ("GET", "/api/bank/entries", None),
    ("POST", "/api/bank/entries", {"kind": "experience", "title": "Lab assistant"}),
    ("POST", "/api/bank/entries/reorder", {"ids": [2, 1]}),
    ("POST", "/api/bank/import", {"text": "Jane Doe, University of Chicago"}),
    ("GET", "/api/bank/entries/1", None),
    ("PATCH", "/api/bank/entries/1", {"title": "Research assistant"}),
    ("DELETE", "/api/bank/entries/1", None),
    ("POST", "/api/bank/entries/1/bullets", {"text": "Built the thing"}),
    ("PATCH", "/api/bank/bullets/1", {"text": "Built the better thing"}),
    ("DELETE", "/api/bank/bullets/1", None),
    ("GET", "/api/job-posts", None),
    ("POST", "/api/job-posts", {"title": "Quantum Intern", "raw_text": "the whole ad"}),
    ("GET", "/api/job-posts/1", None),
    ("PATCH", "/api/job-posts/1", {"organization": "ACME"}),
    ("DELETE", "/api/job-posts/1", None),
    ("POST", "/api/job-posts/1/fetch", None),
    ("POST", "/api/job-posts/1/keywords", None),
    ("GET", "/api/drafts", None),
    ("POST", "/api/drafts", {"name": "For ACME"}),
    ("GET", "/api/drafts/1", None),
    ("PATCH", "/api/drafts/1", {"name": "For ACME, v2"}),
    ("DELETE", "/api/drafts/1", None),
    ("GET", "/api/drafts/1/coverage", None),
    ("GET", "/api/drafts/1/latex", None),
    ("POST", "/api/drafts/1/push", None),
    ("POST", "/api/drafts/1/tailor", None),
    ("GET", "/api/drafts/1/proposals", None),
    ("POST", "/api/proposals/1/resolve", {"action": "apply"}),
]


def test_init_db_creates_the_bank_and_draft_tables(db_path):
    with database.get_db() as conn:
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert set(NEW_TABLES) <= names


def test_running_init_db_again_leaves_the_new_tables_alone(db_path):
    """Startup runs the whole schema every time, so it has to be a no-op."""
    with database.get_db() as conn:
        before = {table: database._column_names(conn, table) for table in NEW_TABLES}

    database.init_db()

    with database.get_db() as conn:
        after = {table: database._column_names(conn, table) for table in NEW_TABLES}
    assert before == after


def test_the_resume_template_setting_is_seeded_with_a_body_marker(db_path):
    template = database.get_setting("resume_template")
    assert template is not None
    assert "%%RESUME-BODY%%" in template
    assert r"\begin{document}" in template


def test_a_job_post_needs_no_listing_behind_it(db_path):
    """The scraper is the only writer of `opportunities`, so a job the user
    pasted in by hand has nothing to link to."""
    with database.get_db() as conn:
        conn.execute("INSERT INTO job_posts (title, raw_text) VALUES ('Intern', 'the ad')")
        row = conn.execute("SELECT opportunity_id FROM job_posts").fetchone()
    assert row["opportunity_id"] is None


def test_a_null_opportunity_id_does_not_collide_with_another_null(db_path):
    with database.get_db() as conn:
        conn.execute("INSERT INTO job_posts (title, raw_text) VALUES ('One', 'a')")
        conn.execute("INSERT INTO job_posts (title, raw_text) VALUES ('Two', 'b')")
        count = conn.execute("SELECT COUNT(*) c FROM job_posts").fetchone()["c"]
    assert count == 2


def test_two_job_posts_cannot_share_one_listing(db_path):
    with database.get_db() as conn:
        conn.execute(
            "INSERT INTO opportunities (title, organization, type, url) "
            "VALUES ('T', 'Org', 'job', 'https://example.com/j/1')"
        )
        opportunity_id = conn.execute("SELECT id FROM opportunities").fetchone()["id"]
        conn.execute(
            "INSERT INTO job_posts (opportunity_id, title, raw_text) VALUES (?, 'One', 'a')",
            (opportunity_id,),
        )

    with pytest.raises(sqlite3.IntegrityError):
        with database.get_db() as conn:
            conn.execute(
                "INSERT INTO job_posts (opportunity_id, title, raw_text) VALUES (?, 'Two', 'b')",
                (opportunity_id,),
            )


def test_deleting_a_bank_entry_takes_its_bullets_with_it(db_path):
    with database.get_db() as conn:
        entry_id = int(conn.execute(
            "INSERT INTO bank_entries (kind, title) VALUES ('experience', 'Lab assistant')"
        ).lastrowid)
        conn.execute("INSERT INTO bank_bullets (entry_id, text) VALUES (?, 'Did a thing')", (entry_id,))
        conn.execute("INSERT INTO bank_bullets (entry_id, text) VALUES (?, 'Did another')", (entry_id,))

    with database.get_db() as conn:
        before = conn.execute("SELECT COUNT(*) c FROM bank_bullets").fetchone()["c"]
        conn.execute("DELETE FROM bank_entries WHERE id = ?", (entry_id,))

    with database.get_db() as conn:
        after = conn.execute("SELECT COUNT(*) c FROM bank_bullets").fetchone()["c"]
    assert before == 2 and after == 0


def test_deleting_a_draft_takes_its_proposals_with_it(db_path):
    with database.get_db() as conn:
        draft_id = int(conn.execute("INSERT INTO resume_drafts (name) VALUES ('d')").lastrowid)
        conn.execute("INSERT INTO draft_proposals (draft_id, kind) VALUES (?, 'tailor')", (draft_id,))
        conn.execute("DELETE FROM resume_drafts WHERE id = ?", (draft_id,))
        remaining = conn.execute("SELECT COUNT(*) c FROM draft_proposals").fetchone()["c"]
    assert remaining == 0


def test_deleting_a_job_post_unlinks_its_drafts_rather_than_deleting_them(db_path):
    with database.get_db() as conn:
        post_id = int(conn.execute(
            "INSERT INTO job_posts (title, raw_text) VALUES ('Intern', 'the ad')"
        ).lastrowid)
        conn.execute("INSERT INTO resume_drafts (name, job_post_id) VALUES ('d', ?)", (post_id,))
        conn.execute("DELETE FROM job_posts WHERE id = ?", (post_id,))
        row = conn.execute("SELECT name, job_post_id FROM resume_drafts").fetchone()
    assert row["name"] == "d"
    assert row["job_post_id"] is None


@pytest.mark.parametrize("method,path,body", STUBBED_ROUTES)
def test_every_builder_route_is_registered_but_not_yet_implemented(app_client, method, path, body):
    response = app_client.request(method, path, json=body)
    assert response.status_code == 501, response.text


def test_the_reorder_route_is_not_mistaken_for_an_entry_id(app_client):
    """`/api/bank/entries/reorder` and `/api/bank/entries/{id}` share a prefix;
    the int-typed route would answer 422 if it were matched first."""
    response = app_client.post("/api/bank/entries/reorder", json={"ids": [2, 1]})
    assert response.status_code == 501
