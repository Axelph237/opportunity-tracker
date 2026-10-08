"""Tailoring a draft to an advertisement, and reading a resume back into the bank.

The run through `/api/drafts/{id}/tailor` is what most of this pins down,
because the property that matters is not what `_validate_ops` returns but what
can end up in a stored draft.
"""

from __future__ import annotations

import json

import pytest

import database
import drafts
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


def answer(monkeypatch, payload, captured: dict | None = None) -> None:
    """Put one canned Claude response behind the tailoring call."""
    def _run(prompt, **_kwargs):
        if captured is not None:
            captured["prompt"] = prompt
        return payload if isinstance(payload, str) else json.dumps(payload)

    monkeypatch.setattr(tailor, "run_claude", _run)


def composed(client, monkeypatch=None) -> tuple[dict, dict, dict]:
    """A draft holding one placed entry, with a second entry still in the bank."""
    placed = make_entry(client, title="Lab assistant")
    make_bullet(client, placed["id"], "Calibrated readout on a 12-qubit device")
    spare = make_entry(client, title="Teaching assistant", kind="experience")
    draft = make_draft(client)
    drafts.place_entry(draft["id"], placed["id"])
    return draft, placed, spare


def placement_of(client, draft_id: int) -> dict:
    body = client.get(f"/api/drafts/{draft_id}").json()["body"]
    return [p for section in body["sections"] for p in section["placements"]][0]


def titles_in(body: dict) -> list[str]:
    return [p["title"] for section in body["sections"] for p in section["placements"]]


# --------------------------------------------- the guarantee: no invented experience

def test_a_hallucinated_entry_id_cannot_reach_the_draft(app_client, monkeypatch):
    """The whole point of the feature, proved end to end.

    The model asks for bank entry 999999, which nobody ever wrote. It must not
    survive into the stored proposal, and applying everything the proposal does
    carry must leave the draft holding only records the student actually has.
    """
    draft, _placed, spare = composed(app_client)
    answer(monkeypatch, {
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
    draft, _placed, _spare = composed(app_client)
    placement = placement_of(app_client, draft["id"])
    answer(monkeypatch, {
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
    """Two tables enumerate one algebra.

    An operation in `drafts.OPERATIONS` with no `OP_SHAPES` row would be
    offered unvalidated; one with a row and no handler would be offered and
    then fail on apply.
    """
    assert set(tailor.OP_SHAPES) == set(drafts.OPERATIONS)


def test_every_shaped_operation_names_something_that_has_to_already_exist():
    """No row in the algebra introduces a record out of nothing."""
    for name, shape in tailor.OP_SHAPES.items():
        anchored = shape.bank_field or shape.placement or shape.section_id
        assert anchored, f"{name} names nothing the bank or the draft already holds"


# ------------------------------------------------------------------ rejection paths

def test_an_operation_with_an_unknown_type_is_dropped_and_counted(app_client, monkeypatch):
    draft, _placed, spare = composed(app_client)
    answer(monkeypatch, {
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
    draft, _placed, _spare = composed(app_client)
    other = make_draft(app_client, name="For somewhere else")
    drafts.place_entry(other["id"], make_entry(app_client, title="Tutor")["id"])
    elsewhere = placement_of(app_client, other["id"])

    answer(monkeypatch, {
        "summary": "One change.",
        "operations": [{"op": "DropEntry", "placement_id": elsewhere["ref"]}],
    })

    response = app_client.post(f"/api/drafts/{draft['id']}/tailor")
    assert response.status_code == 502
    assert titles_in(app_client.get(f"/api/drafts/{draft['id']}").json()["body"]) == [
        "Lab assistant"
    ]


def test_a_rewrite_longer_than_a_bullet_is_dropped(app_client, monkeypatch):
    draft, _placed, spare = composed(app_client)
    placement = placement_of(app_client, draft["id"])
    answer(monkeypatch, {
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
    draft, _placed, spare = composed(app_client)
    placement = placement_of(app_client, draft["id"])
    answer(monkeypatch, {
        "operations": [
            {"op": "RewriteBullet", "placement_id": placement["ref"],
             "bullet_ref": placement["bullets"][0]["ref"], "text": "   "},
            {"op": "AddEntry", "entry_id": spare["id"]},
        ],
    })

    proposal = app_client.post(f"/api/drafts/{draft['id']}/tailor").json()
    assert [op["op"] for op in proposal["operations"]] == ["AddEntry"]


def test_a_rename_naming_a_section_this_draft_does_not_have_is_dropped(app_client, monkeypatch):
    draft, _placed, spare = composed(app_client)
    answer(monkeypatch, {
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
    """An empty proposal would read as "nothing here needs improving"."""
    draft, _placed, _spare = composed(app_client)
    answer(monkeypatch, {
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
    draft, _placed, _spare = composed(app_client)
    answer(monkeypatch, {"summary": "It already reads well.", "operations": []})

    response = app_client.post(f"/api/drafts/{draft['id']}/tailor")
    assert response.status_code == 502
    assert "did not suggest any changes" in response.json()["detail"]


# ----------------------------------------------------------------- the happy path

def test_a_well_formed_response_becomes_a_pending_proposal(app_client, monkeypatch):
    draft, _placed, spare = composed(app_client)
    placement = placement_of(app_client, draft["id"])
    answer(monkeypatch, {
        "summary": "Led with the calibration work and mirrored the advertisement's verbs.",
        "operations": [
            {"op": "RewriteBullet", "placement_id": placement["ref"],
             "bullet_ref": placement["bullets"][0]["ref"],
             "text": "Characterized readout on a 12-qubit device",
             "rationale": "the ad asks for characterization"},
            {"op": "AddEntry", "entry_id": spare["id"], "section": "Research Experience",
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
    draft, _placed, _spare = composed(app_client)
    placement = placement_of(app_client, draft["id"])
    before = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]
    answer(monkeypatch, {
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
    draft, _placed, spare = composed(app_client)
    answer(monkeypatch, {"operations": [{"op": "AddEntry", "entry_id": spare["id"]}]})
    proposal = app_client.post(f"/api/drafts/{draft['id']}/tailor").json()

    declined = [{**op, "accepted": False} for op in proposal["operations"]]
    applied = app_client.post(
        f"/api/proposals/{proposal['id']}/resolve",
        json={"action": "apply", "operations": declined},
    )
    assert titles_in(applied.json()["body"]) == ["Lab assistant"]


def test_the_advertisement_and_the_bank_inventory_both_reach_the_model(app_client, monkeypatch):
    draft, placed, spare = composed(app_client)
    with database.get_db() as conn:
        conn.execute(
            "UPDATE job_posts SET keywords = ?",
            (json.dumps([{"term": "Qiskit", "bucket": "technical", "weight": 0.9,
                          "variants": []}]),),
        )
    captured: dict = {}
    answer(monkeypatch, {"operations": [{"op": "AddEntry", "entry_id": spare["id"]}]}, captured)

    app_client.post(f"/api/drafts/{draft['id']}/tailor")

    prompt = captured["prompt"]
    assert "characterize superconducting qubits" in prompt
    assert f"Entry {spare['id']} (experience): Teaching assistant" in prompt
    assert "Calibrated readout on a 12-qubit device" in prompt
    assert "Technical terms: Qiskit" in prompt
    assert "Terms the draft does not yet use: Qiskit" in prompt
    assert placement_of(app_client, draft["id"])["ref"] in prompt


# --------------------------------------------------------------- upstream failures

def test_a_non_json_response_is_a_502_rather_than_a_500(app_client, monkeypatch):
    draft, _placed, _spare = composed(app_client)
    answer(monkeypatch, "I am afraid I cannot help with that.")

    response = app_client.post(f"/api/drafts/{draft['id']}/tailor")
    assert response.status_code == 502
    assert "Could not tailor this draft" in response.json()["detail"]


@pytest.mark.parametrize("body", ["[]", "3", '{"operations": "soon"}', "null"])
def test_a_shapeless_response_is_a_502_rather_than_a_500(app_client, monkeypatch, body):
    draft, _placed, _spare = composed(app_client)
    answer(monkeypatch, body)

    assert app_client.post(f"/api/drafts/{draft['id']}/tailor").status_code == 502


def test_a_bare_array_of_operations_is_read_as_the_operations(app_client, monkeypatch):
    draft, _placed, spare = composed(app_client)
    answer(monkeypatch, [{"op": "AddEntry", "entry_id": spare["id"]}])

    proposal = app_client.post(f"/api/drafts/{draft['id']}/tailor").json()
    assert [op["entry_id"] for op in proposal["operations"]] == [spare["id"]]
    assert proposal["summary"] == "1 change proposed for this advertisement."


def test_claude_being_unavailable_is_a_503(app_client, monkeypatch):
    draft, _placed, _spare = composed(app_client)

    def _unavailable(*_args, **_kwargs):
        raise ClaudeUnavailable("claude is not installed")

    monkeypatch.setattr(tailor, "run_claude", _unavailable)

    response = app_client.post(f"/api/drafts/{draft['id']}/tailor")
    assert response.status_code == 503
    assert "not installed" in response.json()["detail"]


def test_a_failed_claude_call_is_a_502(app_client, monkeypatch):
    draft, _placed, _spare = composed(app_client)

    def _failed(*_args, **_kwargs):
        raise ClaudeCallError("exit 1")

    monkeypatch.setattr(tailor, "run_claude", _failed)

    assert app_client.post(f"/api/drafts/{draft['id']}/tailor").status_code == 502


# ------------------------------------------------------------------ preconditions

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


# ------------------------------------------------------------------- the normalizer

def test_a_json_true_does_not_become_bank_entry_one():
    """`isinstance(True, int)` is the one wrong id that would pass validation."""
    assert tailor._normalize_op({"op": "AddEntry", "entry_id": True})["entry_id"] is None


@pytest.mark.parametrize("value", ["null", "None", "n/a", "", "   "])
def test_the_words_a_model_uses_for_absence_normalize_to_absence(value):
    assert tailor._normalize_op({"op": "DropEntry", "placement_id": value})["placement_id"] is None


def test_an_operation_that_is_not_an_object_still_counts_as_a_dropped_one():
    """Dropping it here would make the discard count the user sees too small."""
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
    assert set(op) == {"op", "accepted", "rationale", "entry_id", "bullet_id", "section",
                       "section_id", "label", "placement_id", "bullet_ref", "position", "text"}


def test_the_bank_inventory_is_cut_on_whole_lines():
    """Half an inventory line invites a half-guessed id."""
    entries = [
        {"id": n, "kind": "experience", "title": "Record " + "x" * 200, "bullets": []}
        for n in range(1, 200)
    ]
    block = tailor._bank_block(entries)

    assert len(block) <= tailor.MAX_BANK_CHARS
    assert all(line.startswith("Entry ") for line in block.split("\n"))


# ------------------------------------------------------------------- bank import

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
    answer(monkeypatch, IMPORTED)

    response = app_client.post("/api/bank/import", json={"text": RESUME})
    assert response.status_code == 200, response.text
    entries = response.json()["entries"]
    assert [e["title"] for e in entries] == ["Lab Assistant"]
    assert entries[0]["bullets"] == ["Calibrated readout on a 12-qubit device"]

    assert app_client.get("/api/bank/entries").json() == []
    with database.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM bank_bullets").fetchone()["c"] == 0


def test_an_imported_kind_the_registry_does_not_know_snaps_to_experience(app_client, monkeypatch):
    answer(monkeypatch, {"entries": [{"kind": "Volunteer Work", "title": "Food bank"}]})

    entries = app_client.post("/api/bank/import", json={"text": RESUME}).json()["entries"]
    assert entries[0]["kind"] == "experience"


def test_an_imported_kind_the_registry_spells_differently_is_recovered(app_client, monkeypatch):
    answer(monkeypatch, {"entries": [{"kind": "Skill Group", "title": "Languages",
                                      "bullets": ["Python", "C++"]}]})

    entries = app_client.post("/api/bank/import", json={"text": RESUME}).json()["entries"]
    assert entries[0]["kind"] == "skill_group"
    assert entries[0]["bullets"] == ["Python", "C++"]


def test_an_imported_record_with_no_title_is_skipped(app_client, monkeypatch):
    answer(monkeypatch, {"entries": [{"kind": "experience", "title": "  "},
                                     {"kind": "project", "title": "Delphi"}]})

    entries = app_client.post("/api/bank/import", json={"text": RESUME}).json()["entries"]
    assert [e["title"] for e in entries] == ["Delphi"]


def test_importing_with_no_text_is_a_400(app_client):
    response = app_client.post("/api/bank/import", json={"text": "   "})
    assert response.status_code == 400
    assert "Paste the text of a resume" in response.json()["detail"]


def test_importing_with_no_body_at_all_is_a_400(app_client):
    assert app_client.post("/api/bank/import").status_code == 400


def test_importing_a_non_string_is_a_400_rather_than_a_500(app_client):
    assert app_client.post("/api/bank/import", json={"text": {"paste": "here"}}).status_code == 400


def test_a_resume_nothing_can_be_read_out_of_is_a_502(app_client, monkeypatch):
    answer(monkeypatch, {"entries": []})

    response = app_client.post("/api/bank/import", json={"text": RESUME})
    assert response.status_code == 502
    assert "No resume records could be read" in response.json()["detail"]


def test_a_non_json_import_response_is_a_502_rather_than_a_500(app_client, monkeypatch):
    answer(monkeypatch, "Sorry, that does not look like a resume.")

    assert app_client.post("/api/bank/import", json={"text": RESUME}).status_code == 502


def test_claude_being_unavailable_for_an_import_is_a_503(app_client, monkeypatch):
    def _unavailable(*_args, **_kwargs):
        raise ClaudeUnavailable("claude is not installed")

    monkeypatch.setattr(tailor, "run_claude", _unavailable)

    assert app_client.post("/api/bank/import", json={"text": RESUME}).status_code == 503


def test_the_resume_text_reaches_the_model(app_client, monkeypatch):
    captured: dict = {}
    answer(monkeypatch, IMPORTED, captured)

    app_client.post("/api/bank/import", json={"text": RESUME})

    assert "Calibrated readout on a 12-qubit device" in captured["prompt"]
