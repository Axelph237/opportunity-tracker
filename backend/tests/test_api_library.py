"""Every resume as one list, however each one came to exist.

Three things were called a resume and only two were ever listed together: a
draft on the canvas, a document written as source, and a draft that had been
pushed, which was a row in both lists with nothing saying they were one thing.
"""

from __future__ import annotations


def library(client) -> dict[str, dict]:
    response = client.get("/api/resume-library")
    assert response.status_code == 200, response.text
    return {row["name"]: row for row in response.json()}


def push_a_draft(client, name: str) -> dict:
    draft = client.post("/api/drafts", json={"name": name}).json()
    client.post(f"/api/drafts/{draft['id']}/push")
    return draft


def test_an_install_with_nothing_in_it_lists_nothing(app_client):
    assert app_client.get("/api/resume-library").json() == []


def test_a_pushed_draft_is_one_row_and_not_two(app_client):
    """It is a row in the draft list and a row in the resume list. Listing
    both would show the same resume twice under the same name."""
    draft = push_a_draft(app_client, "Composed and pushed")

    # The raw list, not the by-name mapping the other tests use: a dict keyed
    # on name collapses a duplicate into one entry and cannot see this at all.
    rows = app_client.get("/api/resume-library").json()

    assert len(rows) == 1, [row["key"] for row in rows]
    assert rows[0]["draft_id"] == draft["id"]
    assert rows[0]["composed"] is True and rows[0]["pushed"] is True


def test_a_draft_nobody_pushed_is_still_a_resume_you_have(app_client):
    app_client.post("/api/drafts", json={"name": "Never pushed"})

    row = library(app_client)["Never pushed"]

    assert row["composed"] is True
    assert row["pushed"] is False
    assert row["instance_id"] is None
    assert row["key"].startswith("draft:")


def test_a_document_written_as_source_is_listed_beside_them(app_client):
    app_client.post("/api/resumes", json={"name": "Typed by hand"})

    row = library(app_client)["Typed by hand"]

    assert row["composed"] is False
    assert row["pushed"] is True
    assert row["draft_id"] is None


def test_the_key_tells_the_two_halves_apart(app_client):
    """A draft and a resume can share an id, so neither is an identity on its
    own and the list needs one that works across both."""
    app_client.post("/api/resumes", json={"name": "Source"})
    app_client.post("/api/drafts", json={"name": "Draft"})

    rows = library(app_client)

    assert rows["Source"]["key"] == "instance:1"
    assert rows["Draft"]["key"] == "draft:1"


def test_the_scored_resume_is_listed_first(app_client, resume_tmp):
    # `resume_tmp` because marking a resume scored publishes resume-active.pdf,
    # which conftest refuses to let a test write into the real project.
    app_client.post("/api/drafts", json={"name": "Newer draft"})
    scored = app_client.post("/api/resumes", json={"name": "Base"}).json()
    app_client.post(f"/api/resumes/{scored['id']}/default")

    names = [row["name"] for row in app_client.get("/api/resume-library").json()]

    assert names[0] == "Base"


def test_deleting_the_resume_leaves_the_draft_listed_on_its_own(app_client):
    """`ON DELETE SET NULL` unlinks the draft rather than removing it, so the
    work on the canvas has to stay reachable."""
    draft = push_a_draft(app_client, "Pushed then deleted")
    instance_id = app_client.get(f"/api/drafts/{draft['id']}").json()["resume_instance_id"]

    app_client.delete(f"/api/resumes/{instance_id}")

    row = library(app_client)["Pushed then deleted"]
    assert row["pushed"] is False
    assert row["draft_id"] == draft["id"]


def test_the_sidebar_badge_counts_what_the_library_lists(app_client):
    """The badge sits directly above the list. Counting only documents left
    it reading one number while the list showed another."""
    app_client.post("/api/resumes", json={"name": "Typed by hand"})
    push_a_draft(app_client, "Composed and pushed")
    app_client.post("/api/drafts", json={"name": "Never pushed"})

    listed = len(app_client.get("/api/resume-library").json())

    assert listed == 3
    assert app_client.get("/api/stats").json()["resumes"] == listed
