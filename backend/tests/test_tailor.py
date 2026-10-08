"""Tailoring a draft to an advertisement, and reading a resume back into the bank.

The run through `/api/drafts/{id}/tailor` is what most of this pins down,
because the property that matters is not what `_validate_ops` returns but what
can end up in a stored draft.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

import database
import drafts
import main
import models
import tailor
from claude_cli import ClaudeCallError, ClaudeUnavailable

AD = (
    "We are hiring a quantum software intern to characterize superconducting qubits. "
    "You will write Qiskit pulse schedules, analyse readout fidelity and present results."
)


def make_entry(client, **overrides) -> dict:
    payload = {"kind": "experience", "title": "Lab assistant", "organization": "Argonne"}
    payload.update(overrides)
    response = client.post("/api/bank/entries", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def make_bullet(client, entry_id: int, text: str) -> dict:
    response = client.post(f"/api/bank/entries/{entry_id}/bullets", json={"text": text})
    assert response.status_code == 201, response.text
    return response.json()


def make_post(client, **overrides) -> dict:
    payload = {"title": "Quantum Intern", "organization": "IonQ", "raw_text": AD}
    payload.update(overrides)
    response = client.post("/api/job-posts", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def make_draft(client, **overrides) -> dict:
    payload = {"name": "For IonQ", "job_post_id": make_post(client)["id"]}
    payload.update(overrides)
    response = client.post("/api/drafts", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def stub_claude_response(monkeypatch, payload, captured: dict | None = None) -> None:
    def _run(prompt, **_kwargs):
        if captured is not None:
            captured["prompt"] = prompt
        return payload if isinstance(payload, str) else json.dumps(payload)

    monkeypatch.setattr(tailor, "run_claude", _run)


def draft_with_one_placed_entry(client) -> tuple[dict, dict, dict]:
    placed = make_entry(client, title="Lab assistant")
    make_bullet(client, placed["id"], "Calibrated readout on a 12-qubit device")
    spare = make_entry(client, title="Teaching assistant", kind="experience")
    draft = make_draft(client)
    drafts.place_entry(draft["id"], placed["id"])
    # Re-read, so the returned entry carries the bullet just added to it.
    return draft, client.get(f"/api/bank/entries/{placed['id']}").json(), spare


def placement_of(client, draft_id: int) -> dict:
    body = client.get(f"/api/drafts/{draft_id}").json()["body"]
    return [p for section in body["sections"] for p in section["placements"]][0]


def titles_in(body: dict) -> list[str]:
    return [p["title"] for section in body["sections"] for p in section["placements"]]


def test_a_hallucinated_entry_id_cannot_reach_the_draft(app_client, monkeypatch):
    draft, _placed, spare = draft_with_one_placed_entry(app_client)
    stub_claude_response(monkeypatch, {
        "summary": "Leading with the hardware work this advertisement asks for.",
        "operations": [
            {"op": "AddEntry", "entry_id": 999999,
             "rationale": "their quantum optics internship at CERN"},
            {"op": "AddEntry", "entry_id": spare["id"], "rationale": "teaching is on the ad"},
        ],
    })

    proposal = app_client.post(f"/api/drafts/{draft['id']}/tailor").json()
    assert [op["entry_id"] for op in proposal["operations"]] == [spare["id"]]
    assert "Discarded 1 suggestion" in proposal["summary"]

    applied = app_client.post(
        f"/api/proposals/{proposal['id']}/resolve", json={"action": "apply"}
    )
    assert applied.status_code == 200, applied.text
    assert titles_in(applied.json()["body"]) == ["Lab assistant", "Teaching assistant"]


def test_a_hallucinated_bullet_id_cannot_reach_the_draft(app_client, monkeypatch):
    draft, _placed, _spare = draft_with_one_placed_entry(app_client)
    placement = placement_of(app_client, draft["id"])
    stub_claude_response(monkeypatch, {
        "summary": "Pulling across the qubit tuning line.",
        "operations": [
            {"op": "AddBullet", "bullet_id": 4242, "placement_id": placement["ref"],
             "rationale": "tuned a transmon to 5.1 GHz"},
        ],
    })

    response = app_client.post(f"/api/drafts/{draft['id']}/tailor")
    assert response.status_code == 502
    assert "Add the experience to the bank" in response.json()["detail"]

    body = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]
    assert len(body["sections"][0]["placements"][0]["bullets"]) == 1


def test_the_op_table_covers_exactly_the_operations_a_draft_can_apply():
    """An operation in `drafts.OPERATIONS` with no `OP_SHAPES` row would be
    offered unvalidated; one with a row and no handler would be offered and
    then fail on apply.
    """
    assert set(tailor.OP_SHAPES) == set(drafts.OPERATIONS)
    assert {
        name: shape.bank_field
        for name, shape in tailor.OP_SHAPES.items()
        if shape.bank_field
    } == drafts.REQUIRED_BANK_REF


EXPECTED_ALGEBRA = {
    "AddEntry": {"bank_field", "section_label"},
    "DropEntry": {"placement"},
    "MoveEntry": {"placement"},
    "RenameSection": {"section_id", "label"},
    "AddBullet": {"bank_field", "placement", "same_entry"},
    "DropBullet": {"placement", "bullet_ref"},
    "MoveBullet": {"placement", "bullet_ref"},
    "RewriteBullet": {"placement", "bullet_ref", "text"},
}


def test_the_algebra_requires_exactly_these_anchors():
    """Pinned whole rather than sampled.

    Asserting only that each row names *something* let four rows quietly drop
    their second anchor with the suite still green.
    """
    assert {
        name: {field for field, required in asdict(shape).items() if required}
        for name, shape in tailor.OP_SHAPES.items()
    } == EXPECTED_ALGEBRA


def test_an_operation_with_an_unknown_type_is_dropped_and_counted(app_client, monkeypatch):
    draft, _placed, spare = draft_with_one_placed_entry(app_client)
    stub_claude_response(monkeypatch, {
        "summary": "Two changes.",
        "operations": [
            {"op": "DeleteEverything", "placement_id": "whatever"},
            {"op": "AddEntry", "entry_id": spare["id"]},
        ],
    })

    proposal = app_client.post(f"/api/drafts/{draft['id']}/tailor").json()
    assert [op["op"] for op in proposal["operations"]] == ["AddEntry"]
    assert "Discarded 1 suggestion" in proposal["summary"]


def test_an_operation_naming_a_placement_this_draft_does_not_have_is_dropped(
    app_client, monkeypatch
):
    draft, _placed, _spare = draft_with_one_placed_entry(app_client)
    other = make_draft(app_client, name="For somewhere else")
    drafts.place_entry(other["id"], make_entry(app_client, title="Tutor")["id"])
    elsewhere = placement_of(app_client, other["id"])

    stub_claude_response(monkeypatch, {
        "summary": "One change.",
        "operations": [{"op": "DropEntry", "placement_id": elsewhere["ref"]}],
    })

    response = app_client.post(f"/api/drafts/{draft['id']}/tailor")
    assert response.status_code == 502
    assert titles_in(app_client.get(f"/api/drafts/{draft['id']}").json()["body"]) == [
        "Lab assistant"
    ]


def test_a_rewrite_longer_than_a_bullet_is_dropped(app_client, monkeypatch):
    draft, _placed, spare = draft_with_one_placed_entry(app_client)
    placement = placement_of(app_client, draft["id"])
    stub_claude_response(monkeypatch, {
        "summary": "One good change and one essay.",
        "operations": [
            {"op": "RewriteBullet", "placement_id": placement["ref"],
             "bullet_ref": placement["bullets"][0]["ref"],
             "text": "Characterized " + "superconducting qubits " * 40},
            {"op": "AddEntry", "entry_id": spare["id"]},
        ],
    })

    proposal = app_client.post(f"/api/drafts/{draft['id']}/tailor").json()
    assert [op["op"] for op in proposal["operations"]] == ["AddEntry"]


def test_a_rewrite_with_no_text_is_dropped(app_client, monkeypatch):
    draft, _placed, spare = draft_with_one_placed_entry(app_client)
    placement = placement_of(app_client, draft["id"])
    stub_claude_response(monkeypatch, {
        "operations": [
            {"op": "RewriteBullet", "placement_id": placement["ref"],
             "bullet_ref": placement["bullets"][0]["ref"], "text": "   "},
            {"op": "AddEntry", "entry_id": spare["id"]},
        ],
    })

    proposal = app_client.post(f"/api/drafts/{draft['id']}/tailor").json()
    assert [op["op"] for op in proposal["operations"]] == ["AddEntry"]


def test_a_rename_naming_a_section_this_draft_does_not_have_is_dropped(app_client, monkeypatch):
    draft, _placed, spare = draft_with_one_placed_entry(app_client)
    stub_claude_response(monkeypatch, {
        "operations": [
            {"op": "RenameSection", "section_id": "not-a-ref", "label": "Research Experience"},
            {"op": "AddEntry", "entry_id": spare["id"]},
        ],
    })

    proposal = app_client.post(f"/api/drafts/{draft['id']}/tailor").json()
    assert [op["op"] for op in proposal["operations"]] == ["AddEntry"]


def test_a_response_whose_every_operation_is_invalid_is_a_502_not_an_empty_proposal(
    app_client, monkeypatch
):
    draft, _placed, _spare = draft_with_one_placed_entry(app_client)
    stub_claude_response(monkeypatch, {
        "summary": "Added their CERN internship.",
        "operations": [
            {"op": "AddEntry", "entry_id": 777},
            {"op": "AddBullet", "bullet_id": 888, "placement_id": "nope"},
        ],
    })

    response = app_client.post(f"/api/drafts/{draft['id']}/tailor")
    assert response.status_code == 502
    assert "Every one of the 2 suggested changes" in response.json()["detail"]
    with database.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM draft_proposals").fetchone()["c"] == 0


def test_a_response_suggesting_nothing_at_all_is_a_502(app_client, monkeypatch):
    draft, _placed, _spare = draft_with_one_placed_entry(app_client)
    stub_claude_response(monkeypatch, {"summary": "It already reads well.", "operations": []})

    response = app_client.post(f"/api/drafts/{draft['id']}/tailor")
    assert response.status_code == 502
    assert "did not suggest any changes" in response.json()["detail"]


def test_a_well_formed_response_becomes_a_pending_proposal(app_client, monkeypatch):
    draft, _placed, spare = draft_with_one_placed_entry(app_client)
    placement = placement_of(app_client, draft["id"])
    stub_claude_response(monkeypatch, {
        "summary": "Led with the calibration work and mirrored the advertisement's verbs.",
        "operations": [
            {"op": "RewriteBullet", "placement_id": placement["ref"],
             "bullet_ref": placement["bullets"][0]["ref"],
             "text": "Characterized readout on a 12-qubit device",
             "rationale": "the ad asks for characterization"},
            {"op": "AddEntry", "entry_id": spare["id"], "section": "Experience",
             "position": 0, "rationale": "teaching shows the communication they ask for"},
        ],
    })

    response = app_client.post(f"/api/drafts/{draft['id']}/tailor")
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert proposal["kind"] == "tailor"
    assert proposal["status"] == "pending"
    assert len(proposal["operations"]) == 2
    assert all(op["accepted"] for op in proposal["operations"])
    assert proposal["summary"].startswith("Led with the calibration work")
    assert "Discarded" not in proposal["summary"]


def test_the_draft_is_untouched_until_the_proposal_is_applied(app_client, monkeypatch):
    draft, _placed, _spare = draft_with_one_placed_entry(app_client)
    placement = placement_of(app_client, draft["id"])
    before = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]
    stub_claude_response(monkeypatch, {
        "operations": [
            {"op": "RewriteBullet", "placement_id": placement["ref"],
             "bullet_ref": placement["bullets"][0]["ref"],
             "text": "Characterized readout on a 12-qubit device"},
        ],
    })

    proposal = app_client.post(f"/api/drafts/{draft['id']}/tailor").json()
    assert app_client.get(f"/api/drafts/{draft['id']}").json()["body"] == before

    app_client.post(f"/api/proposals/{proposal['id']}/resolve", json={"action": "apply"})
    after = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]
    assert after["sections"][0]["placements"][0]["bullets"][0]["text"] == (
        "Characterized readout on a 12-qubit device"
    )


def test_an_operation_the_user_rejected_is_not_applied(app_client, monkeypatch):
    draft, _placed, spare = draft_with_one_placed_entry(app_client)
    stub_claude_response(monkeypatch, {"operations": [{"op": "AddEntry", "entry_id": spare["id"]}]})
    proposal = app_client.post(f"/api/drafts/{draft['id']}/tailor").json()

    declined = [{**op, "accepted": False} for op in proposal["operations"]]
    applied = app_client.post(
        f"/api/proposals/{proposal['id']}/resolve",
        json={"action": "apply", "operations": declined},
    )
    assert titles_in(applied.json()["body"]) == ["Lab assistant"]


def test_the_advertisement_and_the_bank_inventory_both_reach_the_model(app_client, monkeypatch):
    draft, placed, spare = draft_with_one_placed_entry(app_client)
    with database.get_db() as conn:
        conn.execute(
            "UPDATE job_posts SET keywords = ?",
            (json.dumps([{"term": "Qiskit", "bucket": "technical", "weight": 0.9,
                          "variants": []}]),),
        )
    captured: dict = {}
    stub_claude_response(monkeypatch, {"operations": [{"op": "AddEntry", "entry_id": spare["id"]}]}, captured)

    app_client.post(f"/api/drafts/{draft['id']}/tailor")

    prompt = captured["prompt"]
    assert "characterize superconducting qubits" in prompt
    assert f"Entry {spare['id']} (experience): Teaching assistant" in prompt
    assert "Calibrated readout on a 12-qubit device" in prompt
    assert "Technical terms: Qiskit" in prompt
    assert "Terms the draft does not yet use: Qiskit" in prompt
    assert placement_of(app_client, draft["id"])["ref"] in prompt


def test_a_non_json_response_is_a_502_rather_than_a_500(app_client, monkeypatch):
    draft, _placed, _spare = draft_with_one_placed_entry(app_client)
    stub_claude_response(monkeypatch, "I am afraid I cannot help with that.")

    response = app_client.post(f"/api/drafts/{draft['id']}/tailor")
    assert response.status_code == 502
    assert "Could not tailor this draft" in response.json()["detail"]


@pytest.mark.parametrize("body", ["[]", "3", '{"operations": "soon"}', "null"])
def test_a_shapeless_response_is_a_502_rather_than_a_500(app_client, monkeypatch, body):
    draft, _placed, _spare = draft_with_one_placed_entry(app_client)
    stub_claude_response(monkeypatch, body)

    assert app_client.post(f"/api/drafts/{draft['id']}/tailor").status_code == 502


def test_a_bare_array_of_operations_is_read_as_the_operations(app_client, monkeypatch):
    draft, _placed, spare = draft_with_one_placed_entry(app_client)
    stub_claude_response(monkeypatch, [{"op": "AddEntry", "entry_id": spare["id"]}])

    proposal = app_client.post(f"/api/drafts/{draft['id']}/tailor").json()
    assert [op["entry_id"] for op in proposal["operations"]] == [spare["id"]]
    assert proposal["summary"] == "1 change proposed for this advertisement."


def test_claude_being_unavailable_is_a_503(app_client, monkeypatch):
    draft, _placed, _spare = draft_with_one_placed_entry(app_client)

    def _unavailable(*_args, **_kwargs):
        raise ClaudeUnavailable("claude is not installed")

    monkeypatch.setattr(tailor, "run_claude", _unavailable)

    response = app_client.post(f"/api/drafts/{draft['id']}/tailor")
    assert response.status_code == 503
    assert "not installed" in response.json()["detail"]


def test_a_failed_claude_call_is_a_502(app_client, monkeypatch):
    draft, _placed, _spare = draft_with_one_placed_entry(app_client)

    def _failed(*_args, **_kwargs):
        raise ClaudeCallError("exit 1")

    monkeypatch.setattr(tailor, "run_claude", _failed)

    assert app_client.post(f"/api/drafts/{draft['id']}/tailor").status_code == 502


def test_tailoring_an_unknown_draft_is_a_404(app_client):
    assert app_client.post("/api/drafts/9999/tailor").status_code == 404


def test_a_draft_with_no_job_post_is_a_400(app_client):
    draft = app_client.post("/api/drafts", json={"name": "Unaimed"}).json()

    response = app_client.post(f"/api/drafts/{draft['id']}/tailor")
    assert response.status_code == 400
    assert "not linked to a job post" in response.json()["detail"]


def test_a_job_post_with_no_advertisement_text_is_a_400(app_client):
    post = make_post(app_client, raw_text="   ")
    draft = app_client.post("/api/drafts", json={"name": "d", "job_post_id": post["id"]}).json()

    response = app_client.post(f"/api/drafts/{draft['id']}/tailor")
    assert response.status_code == 400
    assert "no advertisement text" in response.json()["detail"]


def test_an_empty_bank_and_an_empty_draft_is_a_400(app_client):
    draft = make_draft(app_client)

    response = app_client.post(f"/api/drafts/{draft['id']}/tailor")
    assert response.status_code == 400
    assert "Import a resume into the bank first" in response.json()["detail"]


def test_a_json_true_does_not_become_bank_entry_one():
    assert tailor._normalize_op({"op": "AddEntry", "entry_id": True})["entry_id"] is None


@pytest.mark.parametrize("value", ["null", "None", "n/a", "", "   "])
def test_the_words_a_model_uses_for_absence_normalize_to_absence(value):
    assert tailor._normalize_op({"op": "DropEntry", "placement_id": value})["placement_id"] is None


def test_an_operation_that_is_not_an_object_still_counts_as_a_dropped_one():
    ops = tailor._normalize_ops([{"op": "DropEntry"}, "AddEntry", None, 7])
    assert len(ops) == 4
    assert [op["op"] for op in ops] == ["DropEntry", "", "", ""]


def test_a_negative_position_normalizes_to_the_front():
    assert tailor._normalize_op({"op": "MoveEntry", "position": -3})["position"] == 0


def test_a_string_position_is_read_as_a_number():
    assert tailor._normalize_op({"op": "MoveEntry", "position": "2"})["position"] == 2


def test_no_more_than_the_op_cap_is_ever_considered():
    raw = [{"op": "DropEntry"}] * (tailor.MAX_OPS + 10)
    assert len(tailor._normalize_ops(raw)) == tailor.MAX_OPS


def test_a_normalized_op_carries_exactly_the_fields_the_apply_path_reads():
    op = tailor._normalize_op({"op": "AddEntry", "entry_id": 1})
    assert set(op) == set(models.ProposalOp.model_fields)


def test_the_bank_inventory_is_cut_on_whole_lines():
    entries = [
        {"id": n, "kind": "experience", "title": "Record " + "x" * 200, "bullets": []}
        for n in range(1, 200)
    ]
    block = tailor._bank_block(entries)

    assert len(block) <= tailor.MAX_BANK_CHARS
    assert all(line.startswith("Entry ") for line in block.split("\n"))


RESUME = """Jane Doe
Lab Assistant, Argonne National Laboratory, Lemont IL, Jun 2026 - Sep 2026
- Calibrated readout on a 12-qubit device
"""

IMPORTED = {
    "entries": [
        {"kind": "experience", "title": "Lab Assistant", "organization": "Argonne",
         "location": "Lemont, IL", "start_date": "Jun 2026", "end_date": "Sep 2026",
         "is_current": False, "url": None, "detail": None,
         "bullets": ["Calibrated readout on a 12-qubit device"]},
    ]
}


def test_importing_a_resume_returns_a_preview_and_writes_nothing(app_client, monkeypatch):
    stub_claude_response(monkeypatch, IMPORTED)

    response = app_client.post("/api/bank/import", json={"text": RESUME})
    assert response.status_code == 200, response.text
    entries = response.json()["entries"]
    assert [e["title"] for e in entries] == ["Lab Assistant"]
    assert entries[0]["bullets"] == ["Calibrated readout on a 12-qubit device"]

    assert app_client.get("/api/bank/entries").json() == []
    with database.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM bank_bullets").fetchone()["c"] == 0


def test_an_imported_kind_the_registry_does_not_know_snaps_to_experience(app_client, monkeypatch):
    stub_claude_response(monkeypatch, {"entries": [{"kind": "Volunteer Work", "title": "Food bank"}]})

    entries = app_client.post("/api/bank/import", json={"text": RESUME}).json()["entries"]
    assert entries[0]["kind"] == "experience"


def test_an_imported_kind_the_registry_spells_differently_is_recovered(app_client, monkeypatch):
    stub_claude_response(monkeypatch, {"entries": [{"kind": "Skill Group", "title": "Languages",
                                      "bullets": ["Python", "C++"]}]})

    entries = app_client.post("/api/bank/import", json={"text": RESUME}).json()["entries"]
    assert entries[0]["kind"] == "skill_group"
    assert entries[0]["bullets"] == ["Python", "C++"]


def test_an_imported_record_with_no_title_is_skipped(app_client, monkeypatch):
    stub_claude_response(monkeypatch, {"entries": [{"kind": "experience", "title": "  "},
                                     {"kind": "project", "title": "Delphi"}]})

    entries = app_client.post("/api/bank/import", json={"text": RESUME}).json()["entries"]
    assert [e["title"] for e in entries] == ["Delphi"]


@pytest.fixture
def no_stored_resume(monkeypatch):
    """Nothing for the import to fall back to.

    Pinned rather than left alone, so these cases do not quietly read whatever
    resume happens to sit in the developer's checkout.
    """
    monkeypatch.setattr(main, "get_resume_text", lambda: None)


def test_importing_with_nothing_to_read_says_where_to_put_a_resume(app_client, no_stored_resume):
    """The old message asked the user to paste text. The interface has no
    paste box, so it named an action they could not take."""
    response = app_client.post("/api/bank/import", json={"text": "   "})

    assert response.status_code == 400
    assert "Settings" in response.json()["detail"]


def test_importing_with_no_body_at_all_is_a_400(app_client, no_stored_resume):
    assert app_client.post("/api/bank/import").status_code == 400


def test_importing_a_non_string_is_a_400_rather_than_a_500(app_client, no_stored_resume):
    assert app_client.post("/api/bank/import", json={"text": {"paste": "here"}}).status_code == 400


def test_a_resume_nothing_can_be_read_out_of_is_a_502(app_client, monkeypatch):
    stub_claude_response(monkeypatch, {"entries": []})

    response = app_client.post("/api/bank/import", json={"text": RESUME})
    assert response.status_code == 502
    assert "No resume records could be read" in response.json()["detail"]


def test_a_non_json_import_response_is_a_502_rather_than_a_500(app_client, monkeypatch):
    stub_claude_response(monkeypatch, "Sorry, that does not look like a resume.")

    assert app_client.post("/api/bank/import", json={"text": RESUME}).status_code == 502


def test_claude_being_unavailable_for_an_import_is_a_503(app_client, monkeypatch):
    def _unavailable(*_args, **_kwargs):
        raise ClaudeUnavailable("claude is not installed")

    monkeypatch.setattr(tailor, "run_claude", _unavailable)

    assert app_client.post("/api/bank/import", json={"text": RESUME}).status_code == 503


def test_the_resume_text_reaches_the_model(app_client, monkeypatch):
    captured: dict = {}
    stub_claude_response(monkeypatch, IMPORTED, captured)

    app_client.post("/api/bank/import", json={"text": RESUME})

    assert "Calibrated readout on a 12-qubit device" in captured["prompt"]


def test_a_bullet_cannot_be_grafted_onto_an_entry_it_is_not_part_of(app_client, monkeypatch):
    """Real experience under the wrong employer is still a false resume line."""
    draft, _placed, spare = draft_with_one_placed_entry(app_client)
    elsewhere = make_bullet(app_client, spare["id"], "Supervised a team of 12 across three shifts")
    placement = placement_of(app_client, draft["id"])
    stub_claude_response(monkeypatch, {
        "operations": [
            {"op": "AddBullet", "bullet_id": elsewhere["id"], "placement_id": placement["ref"]},
        ],
    })

    assert app_client.post(f"/api/drafts/{draft['id']}/tailor").status_code == 502
    body = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]
    assert [b["text"] for b in body["sections"][0]["placements"][0]["bullets"]] == [
        "Calibrated readout on a 12-qubit device"
    ]


def test_an_add_entry_cannot_invent_a_section_heading(app_client, monkeypatch):
    """`section` reaches `_section_for`, which creates the heading if it is new.

    Retitling a section is `RenameSection`, which the user reviews as its own
    operation rather than as a side effect of placing a record.
    """
    draft, _placed, spare = draft_with_one_placed_entry(app_client)
    stub_claude_response(monkeypatch, {
        "operations": [
            {"op": "AddEntry", "entry_id": spare["id"],
             "section": "Peer-Reviewed Publications in Nature",
             "rationale": "teaching shows the communication they ask for"},
        ],
    })

    assert app_client.post(f"/api/drafts/{draft['id']}/tailor").status_code == 502


def test_an_add_entry_may_name_a_section_the_resume_already_has(app_client, monkeypatch):
    draft, _placed, spare = draft_with_one_placed_entry(app_client)
    stub_claude_response(monkeypatch, {
        "operations": [{"op": "AddEntry", "entry_id": spare["id"], "section": "Experience"}],
    })

    proposal = app_client.post(f"/api/drafts/{draft['id']}/tailor").json()
    applied = app_client.post(
        f"/api/proposals/{proposal['id']}/resolve", json={"action": "apply"}
    ).json()
    assert [s["label"] for s in applied["body"]["sections"]] == ["Experience"]


def test_an_add_bullet_naming_another_drafts_placement_is_dropped(app_client, monkeypatch):
    draft, placed, _spare = draft_with_one_placed_entry(app_client)
    other = make_draft(app_client, name="Elsewhere")
    drafts.place_entry(other["id"], placed["id"])
    elsewhere = placement_of(app_client, other["id"])
    stub_claude_response(monkeypatch, {
        "operations": [
            {"op": "AddBullet", "bullet_id": placed["bullets"][0]["id"],
             "placement_id": elsewhere["ref"]},
        ],
    })

    assert app_client.post(f"/api/drafts/{draft['id']}/tailor").status_code == 502


@pytest.mark.parametrize("op", ["DropBullet", "MoveBullet", "RewriteBullet"])
def test_a_bullet_ref_from_a_different_placement_is_dropped(app_client, monkeypatch, op):
    draft, placed, _spare = draft_with_one_placed_entry(app_client)
    drafts.place_entry(draft["id"], placed["id"])
    body = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]
    first, second = body["sections"][0]["placements"]
    stub_claude_response(monkeypatch, {
        "operations": [
            {"op": op, "placement_id": first["ref"], "bullet_ref": second["bullets"][0]["ref"],
             "text": "Characterized readout on a 12-qubit device"},
        ],
    })

    assert app_client.post(f"/api/drafts/{draft['id']}/tailor").status_code == 502


def test_a_stray_bank_id_on_an_operation_that_never_reads_one_is_stripped(
    app_client, monkeypatch
):
    """The prompt lists `entry_id` for every operation and asks for null on the
    rest. Left in place, it would be stored unvalidated and then make
    `drafts._check_bank_refs` refuse the whole proposal rather than one field.
    """
    draft, _placed, _spare = draft_with_one_placed_entry(app_client)
    placement = placement_of(app_client, draft["id"])
    stub_claude_response(monkeypatch, {
        "operations": [
            {"op": "DropEntry", "placement_id": placement["ref"], "entry_id": 999999,
             "section": "Peer-Reviewed Publications in Nature"},
        ],
    })

    proposal = app_client.post(f"/api/drafts/{draft['id']}/tailor").json()
    assert proposal["operations"][0]["entry_id"] is None
    assert proposal["operations"][0]["section"] is None

    applied = app_client.post(
        f"/api/proposals/{proposal['id']}/resolve", json={"action": "apply"}
    )
    assert applied.status_code == 200, applied.text
    assert titles_in(applied.json()["body"]) == []


@pytest.mark.parametrize("literal", ["1e400", "Infinity", "-Infinity", "1e999"])
def test_an_overflowing_id_is_a_502_rather_than_a_500(app_client, monkeypatch, literal):
    """`json.loads` accepts these and `int()` answers them with OverflowError."""
    draft, _placed, _spare = draft_with_one_placed_entry(app_client)
    stub_claude_response(
        monkeypatch, '{"operations": [{"op": "AddEntry", "entry_id": %s}]}' % literal
    )

    assert app_client.post(f"/api/drafts/{draft['id']}/tailor").status_code == 502


def test_an_overflowing_position_is_a_502_rather_than_a_500(app_client, monkeypatch):
    draft, _placed, _spare = draft_with_one_placed_entry(app_client)
    stub_claude_response(
        monkeypatch, '{"operations": [{"op": "MoveEntry", "position": 1e400}]}'
    )

    assert app_client.post(f"/api/drafts/{draft['id']}/tailor").status_code == 502


def test_a_rationale_longer_than_the_cap_is_truncated():
    op = tailor._normalize_op({"op": "DropEntry", "rationale": "x" * 9000})
    assert len(op["rationale"]) == tailor.MAX_RATIONALE_CHARS


def test_an_import_takes_no_more_than_the_entry_and_bullet_caps():
    data = {"entries": [{"kind": "experience", "title": f"Role {n}",
                         "bullets": [f"did {i}" for i in range(50)]}
                        for n in range(tailor.MAX_IMPORT_ENTRIES + 5)]}
    entries = tailor._normalize_entries(data)

    assert len(entries) == tailor.MAX_IMPORT_ENTRIES
    assert len(entries[0]["bullets"]) == tailor.MAX_IMPORT_BULLETS


def test_a_runaway_rewrite_is_bounded_well_above_the_bullet_cap():
    """`_rejection` compares the normalized length, so the raw cap has to sit
    above the bullet cap or rejection would silently become truncation.
    """
    assert tailor.MAX_RAW_TEXT_CHARS > tailor.MAX_BULLET_CHARS
    assert len(tailor._normalize_op({"op": "RewriteBullet", "text": "x" * 99999})["text"]) == (
        tailor.MAX_RAW_TEXT_CHARS
    )
