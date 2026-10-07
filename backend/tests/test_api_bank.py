"""The experience-bank and draft tables, and the API surface reserved for them."""

from __future__ import annotations

import sqlite3

import pytest

import bank
import database

NEW_TABLES = ("bank_entries", "bank_bullets", "job_posts", "resume_drafts", "draft_proposals")

# Endpoints the builder reserves but has not filled in yet, with a body valid
# enough to reach the handler: a request rejected during validation would
# answer 422 and prove nothing about whether the route is registered.
STUBBED_ROUTES = [
    ("POST", "/api/bank/import", {"text": "Jane Doe, University of Chicago"}),
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
    assert response.status_code == 200
    assert response.json() == []


# ------------------------------------------------------------------- the bank

def make_entry(client, **overrides):
    payload = {"kind": "experience", "title": "Lab assistant"}
    payload.update(overrides)
    response = client.post("/api/bank/entries", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_an_entry_keeps_the_bullets_it_was_created_with_in_order(app_client):
    """Bullets travel with the entry so confirming an import is one request per
    record rather than one per line."""
    entry = make_entry(app_client, bullets=["Ran the rig", "Wrote the analysis"])

    assert [bullet["text"] for bullet in entry["bullets"]] == ["Ran the rig", "Wrote the analysis"]
    assert [bullet["position"] for bullet in entry["bullets"]] == [0, 1]


def test_a_blank_bullet_never_reaches_the_bank(app_client):
    entry = make_entry(app_client, bullets=["Ran the rig", "   ", ""])

    assert [bullet["text"] for bullet in entry["bullets"]] == ["Ran the rig"]


def test_is_current_comes_back_as_a_boolean_not_the_integer_sqlite_stores(app_client):
    entry = make_entry(app_client, is_current=True)

    assert entry["is_current"] is True
    assert app_client.get(f"/api/bank/entries/{entry['id']}").json()["is_current"] is True


def test_a_kind_outside_the_registry_is_refused(db_path):
    """The registry, not a SQL CHECK, decides what a bank entry can be."""
    with pytest.raises(ValueError, match="is not a kind of bank entry"):
        bank.create_entry({"kind": "mixtape", "title": "Summer 2019"})


def test_an_unknown_entry_is_a_404_on_every_verb(app_client):
    assert app_client.get("/api/bank/entries/404").status_code == 404
    assert app_client.patch("/api/bank/entries/404", json={"title": "x"}).status_code == 404
    assert app_client.delete("/api/bank/entries/404").status_code == 404
    assert app_client.post("/api/bank/entries/404/bullets", json={"text": "x"}).status_code == 404


def test_an_unknown_bullet_is_a_404(app_client):
    assert app_client.patch("/api/bank/bullets/404", json={"text": "x"}).status_code == 404
    assert app_client.delete("/api/bank/bullets/404").status_code == 404


def test_entries_list_in_the_order_the_user_arranged_them(app_client):
    first = make_entry(app_client, title="First")
    second = make_entry(app_client, title="Second")
    third = make_entry(app_client, title="Third")

    app_client.post("/api/bank/entries/reorder", json={"ids": [third["id"], first["id"], second["id"]]})

    listed = app_client.get("/api/bank/entries").json()
    assert [entry["title"] for entry in listed] == ["Third", "First", "Second"]


def test_reorder_renumbers_positions_densely_so_none_collide(app_client):
    first = make_entry(app_client, title="First")
    second = make_entry(app_client, title="Second")

    reordered = app_client.post(
        "/api/bank/entries/reorder", json={"ids": [second["id"], first["id"]]}
    ).json()

    assert [entry["position"] for entry in reordered] == [0, 1]


def test_reorder_ignores_an_id_that_no_longer_exists(app_client):
    """The rail the user dragged may be a few seconds stale. Refusing the whole
    drag over one deleted row would lose the rest of the arrangement."""
    first = make_entry(app_client, title="First")
    second = make_entry(app_client, title="Second")

    reordered = app_client.post(
        "/api/bank/entries/reorder", json={"ids": [9999, second["id"], first["id"]]}
    ).json()

    assert [entry["title"] for entry in reordered] == ["Second", "First"]


def test_reorder_keeps_entries_the_caller_left_out(app_client):
    first = make_entry(app_client, title="First")
    second = make_entry(app_client, title="Second")
    third = make_entry(app_client, title="Third")

    reordered = app_client.post(
        "/api/bank/entries/reorder", json={"ids": [third["id"], second["id"]]}
    ).json()

    assert [entry["title"] for entry in reordered] == ["Third", "Second", "First"]


def test_a_new_bullet_lands_at_the_end_of_its_entry(app_client):
    entry = make_entry(app_client, bullets=["One", "Two"])

    app_client.post(f"/api/bank/entries/{entry['id']}/bullets", json={"text": "Three"})

    refreshed = app_client.get(f"/api/bank/entries/{entry['id']}").json()
    assert [bullet["text"] for bullet in refreshed["bullets"]] == ["One", "Two", "Three"]


def test_a_new_bullet_given_a_position_lands_there(app_client):
    entry = make_entry(app_client, bullets=["One", "Three"])

    app_client.post(f"/api/bank/entries/{entry['id']}/bullets", json={"text": "Two", "position": 1})

    refreshed = app_client.get(f"/api/bank/entries/{entry['id']}").json()
    assert [bullet["text"] for bullet in refreshed["bullets"]] == ["One", "Two", "Three"]


def test_a_bullet_moves_among_its_siblings_without_changing_its_text(app_client):
    entry = make_entry(app_client, bullets=["One", "Two", "Three"])
    last = entry["bullets"][2]

    app_client.patch(f"/api/bank/bullets/{last['id']}", json={"position": 0})

    refreshed = app_client.get(f"/api/bank/entries/{entry['id']}").json()
    assert [bullet["text"] for bullet in refreshed["bullets"]] == ["Three", "One", "Two"]


def test_rewording_a_bullet_leaves_its_id_alone(app_client):
    """Drafts anchor their snapshots to the bullet id, so an edit that minted a
    new one would orphan every draft that placed it."""
    entry = make_entry(app_client, bullets=["Assisted with the rig"])
    bullet_id = entry["bullets"][0]["id"]

    app_client.patch(f"/api/bank/bullets/{bullet_id}", json={"text": "Rebuilt the rig"})

    refreshed = app_client.get(f"/api/bank/entries/{entry['id']}").json()
    assert len(refreshed["bullets"]) == 1
    assert refreshed["bullets"][0]["id"] == bullet_id
    assert refreshed["bullets"][0]["text"] == "Rebuilt the rig"


def test_deleting_an_entry_through_the_api_takes_its_bullets_with_it(app_client):
    entry = make_entry(app_client, bullets=["One", "Two"])

    assert app_client.delete(f"/api/bank/entries/{entry['id']}").status_code == 204

    assert app_client.get(f"/api/bank/entries/{entry['id']}").status_code == 404
    assert app_client.patch(
        f"/api/bank/bullets/{entry['bullets'][0]['id']}", json={"text": "x"}
    ).status_code == 404


# ----------------------------------------------------------------- date strings

@pytest.mark.parametrize(
    "entry,expected",
    [
        ({"start_date": "Jun 2026", "end_date": "Sep 2026"}, "Jun 2026 -- Sep 2026"),
        ({"start_date": "Jun 2026", "is_current": True}, "Jun 2026 -- Present"),
        ({"start_date": "Jun 2026", "end_date": "Sep 2026", "is_current": True},
         "Jun 2026 -- Present"),
        ({"start_date": "June 2027"}, "June 2027"),
        ({"end_date": "May 2025"}, "May 2025"),
        ({}, ""),
    ],
)
def test_the_printed_date_string_covers_every_shape_a_record_has(entry, expected):
    assert bank.format_dates(entry) == expected
