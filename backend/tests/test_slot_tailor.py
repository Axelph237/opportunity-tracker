"""Tailoring a document by rearranging its slots.

The guarantee carried over from the draft tailoring this replaces: an
operation may only name what the bank already holds, so a proposal cannot put
experience into a resume the user never entered. Two new ones come with the
document being the truth. A block is addressed by position, so a proposal is
only valid against the document it was built from. And a block has no
provenance, so the record behind one is recovered by matching rather than
assumed.
"""

from __future__ import annotations

import json

import pytest

import slot_tailor

DOC = r"""\documentclass{article}
\begin{document}
\resumeSubHeadingListStart
% <<slot experience>>
% <</slot>>
\resumeSubHeadingListEnd
Prose nothing may touch.
\end{document}
"""


def stub_claude(monkeypatch, payload, captured: dict | None = None) -> None:
    def _run(prompt, **_kwargs):
        if captured is not None:
            captured["prompt"] = prompt
        return payload if isinstance(payload, str) else json.dumps(payload)

    monkeypatch.setattr(slot_tailor, "run_claude", _run)


def tailorable(client) -> tuple[int, dict]:
    """A document with one record in its slot, and an ad attached."""
    post = client.post("/api/job-posts", json={"title": "ML Engineer", "raw_text": "PyTorch"}).json()
    client.post(f"/api/job-posts/{post['id']}/keywords") if False else None
    made = client.post("/api/resumes", json={"name": "Tailorable"}).json()
    client.patch(f"/api/resumes/{made['id']}", json={"latex": DOC, "job_post_id": post["id"]})
    entry = client.post("/api/bank/entries", json={
        "kind": "experience", "title": "Research Assistant", "organization": "UChicago PME",
        "start_date": "Jun 2025", "is_current": True,
        "bullets": ["Helped with the pipeline", "Built data ingestion"],
    }).json()
    client.post(f"/api/resumes/{made['id']}/slots/experience/placements",
                json={"entry_id": entry["id"]})
    return made["id"], entry


def blocks_of(client, instance_id: int) -> list[dict]:
    rows = client.get(f"/api/resumes/{instance_id}/slots").json()
    return rows[0]["blocks"]


# -------------------------------------------------------- the one guarantee

def test_an_operation_naming_a_record_the_bank_does_not_hold_never_reaches_the_resume(
    app_client, monkeypatch
):
    """The structural form of 'never invent experience'. Deleting the bank
    check in `_rejection` has to make this fail."""
    instance_id, _ = tailorable(app_client)
    stub_claude(monkeypatch, {"summary": "x", "operations": [
        {"op": "AddEntry", "slot": "experience", "entry_id": 99999, "rationale": "invented"},
    ]})

    response = app_client.post(f"/api/resumes/{instance_id}/tailor")

    assert response.status_code == 422
    assert "nothing" in response.json()["detail"].lower()


def test_every_operation_the_algebra_allows_is_covered_by_a_shape(app_client):
    """A ninth operation is a row in OP_SHAPES and a row here, not a branch."""
    assert set(slot_tailor.OP_SHAPES) == {
        "AddEntry", "DropEntry", "MoveEntry",
        "AddBullet", "DropBullet", "MoveBullet", "RewriteBullet",
    }


def test_an_operation_the_algebra_does_not_have_is_refused(app_client, monkeypatch):
    instance_id, _ = tailorable(app_client)
    stub_claude(monkeypatch, {"summary": "x", "operations": [
        {"op": "RenameSection", "slot": "experience", "label": "Anything"},
    ]})

    assert app_client.post(f"/api/resumes/{instance_id}/tailor").status_code == 422


def test_a_block_that_is_not_in_the_slot_is_refused(app_client, monkeypatch):
    instance_id, _ = tailorable(app_client)
    stub_claude(monkeypatch, {"summary": "x", "operations": [
        {"op": "DropEntry", "slot": "experience", "block": 7},
    ]})

    assert app_client.post(f"/api/resumes/{instance_id}/tailor").status_code == 422


def test_a_slot_the_document_does_not_have_is_refused(app_client, monkeypatch):
    instance_id, _ = tailorable(app_client)
    stub_claude(monkeypatch, {"summary": "x", "operations": [
        {"op": "DropEntry", "slot": "education", "block": 0},
    ]})

    assert app_client.post(f"/api/resumes/{instance_id}/tailor").status_code == 422


def test_a_bullet_cannot_be_moved_under_a_record_it_is_not_part_of(app_client, monkeypatch):
    """The document stores no provenance, so the record behind a block is
    recovered by matching. A bullet belonging to someone else is still
    refused."""
    instance_id, _ = tailorable(app_client)
    other = app_client.post("/api/bank/entries", json={
        "kind": "experience", "title": "QA Intern", "organization": "Northrop",
        "bullets": ["Automated a regression suite"],
    }).json()
    stub_claude(monkeypatch, {"summary": "x", "operations": [
        {"op": "AddBullet", "slot": "experience", "block": 0,
         "bullet_id": other["bullets"][0]["id"]},
    ]})

    assert app_client.post(f"/api/resumes/{instance_id}/tailor").status_code == 422


# ------------------------------------------------------------- applying it

def test_an_accepted_rewrite_reaches_the_document(app_client, monkeypatch):
    instance_id, _ = tailorable(app_client)
    stub_claude(monkeypatch, {"summary": "Leads with the build", "operations": [
        {"op": "RewriteBullet", "slot": "experience", "block": 0, "bullet": 0,
         "text": "Rebuilt the pipeline", "rationale": "drops a weak verb"},
    ]})
    proposal = app_client.post(f"/api/resumes/{instance_id}/tailor").json()

    resolved = app_client.post(f"/api/resume-proposals/{proposal['id']}/resolve",
                               json={"action": "apply"})

    assert resolved.status_code == 200, resolved.text
    assert blocks_of(app_client, instance_id)[0]["bullets_text"][0] == "Rebuilt the pipeline"


def test_an_unticked_operation_is_not_run(app_client, monkeypatch):
    instance_id, _ = tailorable(app_client)
    stub_claude(monkeypatch, {"summary": "x", "operations": [
        {"op": "DropBullet", "slot": "experience", "block": 0, "bullet": 0},
    ]})
    proposal = app_client.post(f"/api/resumes/{instance_id}/tailor").json()
    ops = [dict(op, accepted=False) for op in proposal["operations"]]

    app_client.post(f"/api/resume-proposals/{proposal['id']}/resolve",
                    json={"action": "apply", "operations": ops})

    assert len(blocks_of(app_client, instance_id)[0]["bullets"]) == 2


def test_applying_leaves_the_prose_outside_the_slot_alone(app_client, monkeypatch):
    instance_id, _ = tailorable(app_client)
    stub_claude(monkeypatch, {"summary": "x", "operations": [
        {"op": "DropEntry", "slot": "experience", "block": 0},
    ]})
    proposal = app_client.post(f"/api/resumes/{instance_id}/tailor").json()

    app_client.post(f"/api/resume-proposals/{proposal['id']}/resolve", json={"action": "apply"})

    source = app_client.get(f"/api/resumes/{instance_id}").json()["latex"]
    assert "Prose nothing may touch." in source
    assert "% <<slot experience>>" in source


def test_two_drops_in_one_proposal_both_land_on_what_they_named(app_client, monkeypatch):
    """Operations address the snapshot. Applying the first must not shift the
    block the second one named."""
    instance_id, entry = tailorable(app_client)
    second = app_client.post("/api/bank/entries", json={
        "kind": "experience", "title": "QA Intern", "organization": "Northrop", "bullets": ["x"],
    }).json()
    app_client.post(f"/api/resumes/{instance_id}/slots/experience/placements",
                    json={"entry_id": second["id"]})
    stub_claude(monkeypatch, {"summary": "x", "operations": [
        {"op": "DropEntry", "slot": "experience", "block": 0},
        {"op": "DropEntry", "slot": "experience", "block": 1},
    ]})
    proposal = app_client.post(f"/api/resumes/{instance_id}/tailor").json()

    app_client.post(f"/api/resume-proposals/{proposal['id']}/resolve", json={"action": "apply"})

    assert blocks_of(app_client, instance_id) == []


def test_a_document_that_moved_since_the_offer_refuses_the_whole_thing(app_client, monkeypatch):
    """An operation names a position. Applying it to a document that changed
    underneath would land it on a different line."""
    instance_id, entry = tailorable(app_client)
    stub_claude(monkeypatch, {"summary": "x", "operations": [
        {"op": "DropBullet", "slot": "experience", "block": 0, "bullet": 0},
    ]})
    proposal = app_client.post(f"/api/resumes/{instance_id}/tailor").json()
    app_client.post(f"/api/resumes/{instance_id}/slots/experience/placements",
                    json={"entry_id": entry["id"], "position": 0})

    response = app_client.post(f"/api/resume-proposals/{proposal['id']}/resolve",
                               json={"action": "apply"})

    assert response.status_code == 409
    assert "changed since" in response.json()["detail"]


def test_a_resume_with_no_ad_attached_says_so_rather_than_tailoring_to_nothing(app_client):
    made = app_client.post("/api/resumes", json={"name": "No ad"}).json()
    app_client.patch(f"/api/resumes/{made['id']}", json={"latex": DOC})

    response = app_client.post(f"/api/resumes/{made['id']}/tailor")

    assert response.status_code == 422
    assert "job ad" in response.json()["detail"]


def test_a_resume_with_no_slots_says_so_rather_than_offering_nothing(app_client):
    post = app_client.post("/api/job-posts", json={"title": "x", "raw_text": "y"}).json()
    made = app_client.post("/api/resumes", json={"name": "No slots"}).json()
    app_client.patch(f"/api/resumes/{made['id']}",
                     json={"latex": "\\documentclass{article}", "job_post_id": post["id"]})

    response = app_client.post(f"/api/resumes/{made['id']}/tailor")

    assert response.status_code == 422
    assert "no slots" in response.json()["detail"]


# ---------------------------------------------------------------- coverage

def test_coverage_measures_the_document_against_its_ad(app_client):
    instance_id, _ = tailorable(app_client)
    post_id = app_client.get(f"/api/resumes/{instance_id}").json()["job_post_id"]
    app_client.patch(f"/api/job-posts/{post_id}", json={
        "keywords": [{"term": "data ingestion", "bucket": "technical"},
                     {"term": "Rust", "bucket": "technical"}],
    })

    report = app_client.get(f"/api/resumes/{instance_id}/coverage").json()

    assert report["total"] == 2
    assert report["covered"] == 1
    assert [row["covered"] for row in report["keywords"]] == [True, False]


def test_coverage_reads_what_the_slots_say_not_the_whole_file(app_client):
    """Prose sitting outside every slot is not a claim the resume makes about
    the candidate, so it must not count as covering a term. `Prose nothing
    may touch.` is in this document and outside its only slot."""
    instance_id, _ = tailorable(app_client)
    post_id = app_client.get(f"/api/resumes/{instance_id}").json()["job_post_id"]
    app_client.patch(f"/api/job-posts/{post_id}",
                     json={"keywords": [{"term": "Prose", "bucket": "technical"}]})

    report = app_client.get(f"/api/resumes/{instance_id}/coverage").json()

    assert report["covered"] == 0


def test_a_document_with_no_ad_reports_nothing_rather_than_failing(app_client):
    made = app_client.post("/api/resumes", json={"name": "No ad"}).json()

    report = app_client.get(f"/api/resumes/{made['id']}/coverage").json()

    assert report == {"resume_instance_id": made["id"], "job_post_id": None,
                      "covered": 0, "total": 0, "keywords": []}
