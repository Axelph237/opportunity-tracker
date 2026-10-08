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


# ------------------------------------------------- detaching from the canvas

def test_detaching_leaves_the_document_and_keeps_the_canvas_work(app_client):
    """Composing is lossy one way, so this choice has to be made once rather
    than recur as a refused push. Nothing is destroyed either way."""
    draft = push_a_draft(app_client, "Composed and pushed")
    instance_id = app_client.get(f"/api/drafts/{draft['id']}").json()["resume_instance_id"]

    response = app_client.post(f"/api/drafts/{draft['id']}/detach")

    assert response.status_code == 200, response.text
    assert app_client.get(f"/api/resumes/{instance_id}").json()["draft_id"] is None
    assert app_client.get(f"/api/drafts/{draft['id']}").json()["resume_instance_id"] is None


def test_a_detached_pair_is_two_resumes_because_it_now_is_two_things(app_client):
    draft = push_a_draft(app_client, "Composed and pushed")

    app_client.post(f"/api/drafts/{draft['id']}/detach")

    rows = app_client.get("/api/resume-library").json()
    assert sorted((row["composed"], row["pushed"]) for row in rows) == [(False, True), (True, False)]


def test_a_push_after_detaching_writes_a_new_resume_rather_than_the_old_one(app_client):
    """The whole point: the document is free of the canvas and the canvas is
    free of the document, so neither overwrites the other again."""
    draft = push_a_draft(app_client, "Composed and pushed")
    first = app_client.get(f"/api/drafts/{draft['id']}").json()["resume_instance_id"]
    app_client.post(f"/api/drafts/{draft['id']}/detach")

    second = app_client.post(f"/api/drafts/{draft['id']}/push").json()["resume_instance_id"]

    assert second != first


def test_detaching_a_draft_that_was_never_pushed_is_refused(app_client):
    draft = app_client.post("/api/drafts", json={"name": "Never pushed"}).json()

    response = app_client.post(f"/api/drafts/{draft['id']}/detach")

    assert response.status_code == 400
    assert "not attached" in response.json()["detail"]


def test_a_name_another_resume_holds_never_blocks_the_push(app_client):
    """After a detach the old document still holds the draft's name. Letting
    the sync fail there would make the name the thing that stops the work."""
    draft = push_a_draft(app_client, "Composed and pushed")
    app_client.post(f"/api/drafts/{draft['id']}/detach")
    second = app_client.post(f"/api/drafts/{draft['id']}/push")

    assert second.status_code == 200, second.text

    again = app_client.post(f"/api/drafts/{draft['id']}/push")
    assert again.status_code == 200, again.text
    # Two resumes: the document left behind under the original name, and the
    # one the canvas now writes to under the free name `_unique_name` picked.
    names = sorted(row["name"] for row in app_client.get("/api/resume-library").json())
    assert names == ["Composed and pushed", "Composed and pushed 2"]
