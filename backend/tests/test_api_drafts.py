"""Composing a draft, reviewing proposals against it, and pushing it out."""

from __future__ import annotations

import json

import pytest

import bank
import database
import drafts
import resumes


def make_entry(client, **overrides) -> dict:
    payload = {"kind": "experience", "title": "Lab assistant",
               "organization": "Argonne", "location": "Lemont, IL",
               "start_date": "Jun 2026", "end_date": "Sep 2026"}
    payload.update(overrides)
    response = client.post("/api/bank/entries", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def make_draft(client, **overrides) -> dict:
    payload = {"name": "For ACME"}
    payload.update(overrides)
    response = client.post("/api/drafts", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def make_proposal(draft_id: int, operations: list[dict], kind: str = "tailor") -> int:
    """A proposal row straight into the table.

    The tailoring pass that will author these belongs to a later workstream;
    what is under test here is the review and apply path, which has to hold
    whatever that pass eventually produces.
    """
    with database.get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO draft_proposals (draft_id, kind, operations) VALUES (?, ?, ?)",
            (draft_id, kind, json.dumps(operations)),
        )
        return int(cursor.lastrowid)


def only_placement(client, draft_id: int) -> dict:
    body = client.get(f"/api/drafts/{draft_id}").json()["body"]
    placements = [p for section in body["sections"] for p in section["placements"]]
    assert len(placements) == 1, placements
    return placements[0]


def resolve(client, proposal_id: int, **payload):
    return client.post(f"/api/proposals/{proposal_id}/resolve", json={"action": "apply", **payload})


# ---------------------------------------------------------------- draft CRUD

def test_a_new_draft_starts_with_an_empty_body(app_client):
    draft = make_draft(app_client)

    assert draft["body"] == {"sections": []}
    assert draft["pushed_latex"] is None


@pytest.mark.parametrize("stored", ["{not json", "[]", '"a string"'])
def test_a_draft_whose_stored_body_is_not_a_document_refuses_to_be_read(app_client, stored):
    """Reading it as an empty document is worse than failing: the next push
    writes that empty document over the user's variant and reports success."""
    draft = make_draft(app_client)
    with database.get_db() as conn:
        conn.execute("UPDATE resume_drafts SET body = ? WHERE id = ?", (stored, draft["id"]))

    with pytest.raises(drafts.CorruptDraft):
        drafts.get_draft(draft["id"])


def test_one_corrupt_draft_does_not_take_the_list_down_with_it(app_client):
    """Every healthy draft is reachable only through the picker, so a list
    that dies on one bad row leaves them intact and unreachable. Nothing a
    push writes comes from here; every write re-reads the body strictly."""
    good = make_draft(app_client, name="Still fine")
    bad = make_draft(app_client, name="Damaged")
    with database.get_db() as conn:
        conn.execute("UPDATE resume_drafts SET body = '{not json' WHERE id = ?", (bad["id"],))

    listed = app_client.get("/api/drafts")

    assert listed.status_code == 200, listed.text
    assert {row["name"] for row in listed.json()} == {"Still fine", "Damaged"}
    assert app_client.get(f"/api/drafts/{good['id']}").status_code == 200
    with pytest.raises(drafts.CorruptDraft):
        drafts.get_draft(bad["id"])


def test_a_proposal_whose_operations_will_not_parse_can_still_be_dismissed(app_client):
    """Dismissing needs nothing out of that column, and an unreadable
    proposal is the one the user most needs to be rid of."""
    draft = make_draft(app_client)
    proposal_id = make_proposal(draft["id"], [])
    with database.get_db() as conn:
        conn.execute("UPDATE draft_proposals SET operations = '{' WHERE id = ?", (proposal_id,))

    response = app_client.post(f"/api/proposals/{proposal_id}/resolve", json={"action": "dismiss"})

    assert response.status_code == 200, response.text
    listed = app_client.get(f"/api/drafts/{draft['id']}/proposals").json()
    assert [p["status"] for p in listed] == ["dismissed"]


def test_a_proposal_whose_operations_will_not_parse_refuses_to_be_read(app_client):
    draft = make_draft(app_client)
    proposal_id = make_proposal(draft["id"], [])
    with database.get_db() as conn:
        conn.execute("UPDATE draft_proposals SET operations = '{' WHERE id = ?", (proposal_id,))

    with pytest.raises(drafts.CorruptDraft):
        drafts.get_proposal(proposal_id)


def test_a_draft_cannot_be_attached_to_a_job_post_that_is_not_there(app_client):
    """SQLite refuses the link too, but its IntegrityError names no field and
    comes back as a 500 the user cannot act on."""
    response = app_client.post("/api/drafts", json={"name": "For ACME", "job_post_id": 999})

    assert response.status_code == 400, response.text
    assert "job post 999" in response.json()["detail"]


def test_a_draft_cannot_be_pointed_at_a_resume_that_is_not_there(app_client):
    draft = make_draft(app_client)

    response = app_client.patch(f"/api/drafts/{draft['id']}", json={"resume_instance_id": 999})

    assert response.status_code == 400, response.text
    assert "resume 999" in response.json()["detail"]


def test_an_unknown_draft_is_a_404_on_every_verb(app_client):
    assert app_client.get("/api/drafts/404").status_code == 404
    assert app_client.patch("/api/drafts/404", json={"name": "x"}).status_code == 404
    assert app_client.delete("/api/drafts/404").status_code == 404
    assert app_client.get("/api/drafts/404/latex").status_code == 404
    assert app_client.get("/api/drafts/404/coverage").status_code == 404
    assert app_client.get("/api/drafts/404/proposals").status_code == 404
    assert app_client.post("/api/drafts/404/push").status_code == 404


def test_a_body_posted_without_refs_gets_them_minted(app_client):
    """Every operation addresses placements by ref. A body saved without them
    would be a draft no proposal could act on."""
    draft = make_draft(app_client)
    posted = {"sections": [{"ref": "", "label": "Experience", "placements": [
        {"ref": "", "kind": "experience", "title": "Lab assistant",
         "bullets": [{"ref": "", "text": "Ran the rig"}]},
    ]}]}

    saved = app_client.patch(f"/api/drafts/{draft['id']}", json={"body": posted}).json()["body"]

    section = saved["sections"][0]
    placement = section["placements"][0]
    assert section["ref"] and placement["ref"] and placement["bullets"][0]["ref"]


def test_saving_a_draft_leaves_the_refs_it_already_had_alone(app_client):
    """The frontend saves the whole body after every drag. Minting fresh refs
    on the way through would silently orphan every pending proposal."""
    draft, _entry, placement = placed(app_client, bullets=("One", "Two"))
    body = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]
    body["sections"][0]["placements"][0]["bullets"].reverse()

    saved = app_client.patch(f"/api/drafts/{draft['id']}", json={"body": body}).json()["body"]

    reordered = saved["sections"][0]["placements"][0]
    assert reordered["ref"] == placement["ref"]
    assert [bullet["ref"] for bullet in reordered["bullets"]] == [
        placement["bullets"][1]["ref"], placement["bullets"][0]["ref"]
    ]


def test_two_placements_that_arrive_with_the_same_ref_are_separated(app_client):
    """A duplicate ref makes one of the two unaddressable, so an operation
    aimed at the second would silently rewrite the first."""
    draft = make_draft(app_client)
    posted = {"sections": [{"ref": "s", "label": "Experience", "placements": [
        {"ref": "same", "kind": "experience", "title": "One", "bullets": []},
        {"ref": "same", "kind": "experience", "title": "Two", "bullets": []},
    ]}]}

    saved = app_client.patch(f"/api/drafts/{draft['id']}", json={"body": posted}).json()["body"]

    refs = [placement["ref"] for placement in saved["sections"][0]["placements"]]
    assert len(set(refs)) == 2


# ----------------------------------------------------------- the placements route

def test_placing_an_entry_over_http_puts_it_on_the_canvas(app_client):
    """The composer's only way to take something out of the bank. No route was
    ever registered for it, so the rail had nowhere to drop."""
    draft = make_draft(app_client)
    entry = make_entry(app_client, bullets=["Ran the rig"])

    response = app_client.post(f"/api/drafts/{draft['id']}/placements",
                               json={"entry_id": entry["id"]})

    assert response.status_code == 201, response.text
    section = response.json()["body"]["sections"][0]
    assert section["label"] == "Experience"
    assert [p["title"] for p in section["placements"]] == ["Lab assistant"]
    assert [b["text"] for b in section["placements"][0]["bullets"]] == ["Ran the rig"]


def test_placing_an_entry_into_a_named_section_files_it_there(app_client):
    draft = make_draft(app_client)
    first = make_entry(app_client, kind="project", title="Delphi")
    app_client.post(f"/api/drafts/{draft['id']}/placements", json={"entry_id": first["id"]})
    projects = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]["sections"][0]
    second = make_entry(app_client, title="Lab assistant")

    response = app_client.post(f"/api/drafts/{draft['id']}/placements",
                               json={"entry_id": second["id"], "section_ref": projects["ref"]})

    sections = response.json()["body"]["sections"]
    assert [s["label"] for s in sections] == ["Projects"]
    assert [p["title"] for p in sections[0]["placements"]] == ["Delphi", "Lab assistant"]


def test_placing_over_http_reports_an_unknown_draft_and_an_unknown_entry(app_client):
    entry = make_entry(app_client)
    draft = make_draft(app_client)

    assert app_client.post("/api/drafts/999/placements",
                           json={"entry_id": entry["id"]}).status_code == 404
    assert app_client.post(f"/api/drafts/{draft['id']}/placements",
                           json={"entry_id": 999}).status_code == 404
    assert app_client.post(f"/api/drafts/{draft['id']}/placements",
                           json={"entry_id": entry["id"], "section_ref": "nope"}).status_code == 400


# ------------------------------------------------------------------ snapshots

def test_placing_an_entry_files_it_under_the_section_its_kind_belongs_to(app_client):
    draft = make_draft(app_client)
    entry = make_entry(app_client, kind="project", title="Delphi")

    drafts.place_entry(draft["id"], entry["id"])

    body = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]
    assert [section["label"] for section in body["sections"]] == ["Projects"]


def test_placing_an_entry_prints_its_dates_once_rather_than_on_every_render(app_client):
    draft = make_draft(app_client)
    entry = make_entry(app_client, start_date="Jun 2026", is_current=True)

    drafts.place_entry(draft["id"], entry["id"])

    assert only_placement(app_client, draft["id"])["dates"] == "Jun 2026 – Present"


def test_placing_an_entry_snapshots_its_text_so_a_later_bank_edit_leaves_it_alone(app_client):
    """The whole reason a draft stores text rather than a reference. A resume
    already sent must not change because the bank changed behind it."""
    draft = make_draft(app_client)
    entry = make_entry(app_client, bullets=["Assisted with the rig"])
    drafts.place_entry(draft["id"], entry["id"])

    app_client.patch(f"/api/bank/bullets/{entry['bullets'][0]['id']}", json={"text": "Rebuilt the rig"})
    app_client.patch(f"/api/bank/entries/{entry['id']}", json={"title": "Research assistant"})

    placement = only_placement(app_client, draft["id"])
    assert placement["title"] == "Lab assistant"
    assert placement["bullets"][0]["text"] == "Assisted with the rig"


def test_a_snapshot_records_where_each_bullet_came_from(app_client):
    draft = make_draft(app_client)
    entry = make_entry(app_client, bullets=["Ran the rig"])

    drafts.place_entry(draft["id"], entry["id"])

    bullet = only_placement(app_client, draft["id"])["bullets"][0]
    assert bullet["source_bullet_id"] == entry["bullets"][0]["id"]
    assert bullet["source_text"] == "Ran the rig"


def test_a_renamed_section_still_takes_the_next_entry_of_its_kind(app_client):
    """Renaming Experience to suit the job is the documented reason sections
    are renameable. Filing by label meant the next experience placed after a
    rename opened a second section with the old name beside the renamed one."""
    draft = make_draft(app_client)
    first = make_entry(app_client, title="Lab assistant")
    drafts.place_entry(draft["id"], first["id"])
    section = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]["sections"][0]
    resolve(app_client, make_proposal(draft["id"], [
        {"op": "RenameSection", "section_id": section["ref"], "label": "Research Experience"},
    ]))

    drafts.place_entry(draft["id"], make_entry(app_client, title="Teaching assistant")["id"])

    sections = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]["sections"]
    assert [s["label"] for s in sections] == ["Research Experience"]
    assert [p["title"] for p in sections[0]["placements"]] == ["Lab assistant", "Teaching assistant"]


def test_renaming_a_section_on_the_canvas_keeps_its_key(app_client):
    """The canvas renames by saving the whole body back. The key has to
    survive that round trip or the rename splits the section anyway."""
    draft = make_draft(app_client)
    drafts.place_entry(draft["id"], make_entry(app_client, title="Lab assistant")["id"])
    body = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]
    body["sections"][0]["label"] = "Research Experience"
    saved = app_client.patch(f"/api/drafts/{draft['id']}", json={"body": body}).json()
    assert saved["body"]["sections"][0]["key"] == "Experience"

    drafts.place_entry(draft["id"], make_entry(app_client, title="Teaching assistant")["id"])

    sections = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]["sections"]
    assert [s["label"] for s in sections] == ["Research Experience"]
    assert [p["title"] for p in sections[0]["placements"]] == ["Lab assistant", "Teaching assistant"]


def test_a_section_the_client_sent_without_a_key_still_takes_its_entries(app_client):
    """The canvas saves whole bodies, and a body composed before keys existed
    carries none. Such a section is filed under the label it was created with
    rather than being passed over for a fresh one."""
    draft = make_draft(app_client)
    app_client.patch(f"/api/drafts/{draft['id']}", json={"body": {"sections": [
        {"ref": "s1", "label": "Experience", "placements": []},
    ]}})

    drafts.place_entry(draft["id"], make_entry(app_client)["id"])

    sections = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]["sections"]
    assert [len(s["placements"]) for s in sections] == [1]


def test_placing_an_entry_into_a_section_that_does_not_exist_is_refused(app_client):
    draft = make_draft(app_client)
    entry = make_entry(app_client)

    with pytest.raises(ValueError, match="no section"):
        drafts.place_entry(draft["id"], entry["id"], section_ref="nope")


def test_placing_an_entry_the_bank_does_not_hold_is_refused(app_client):
    draft = make_draft(app_client)

    with pytest.raises(bank.BankNotFound):
        drafts.place_entry(draft["id"], 9999)


# ---------------------------------------------------------------------- drift

def test_a_sync_proposal_names_the_drifted_bullets_and_only_those(app_client):
    draft = make_draft(app_client)
    entry = make_entry(app_client, bullets=["Assisted with the rig", "Wrote the analysis"])
    drafts.place_entry(draft["id"], entry["id"])
    app_client.patch(f"/api/bank/bullets/{entry['bullets'][0]['id']}", json={"text": "Rebuilt the rig"})

    proposal = drafts.sync_proposal(draft["id"])

    assert proposal["kind"] == "sync"
    assert [op["text"] for op in proposal["operations"]] == ["Rebuilt the rig"]
    assert [op["op"] for op in proposal["operations"]] == ["RewriteBullet"]


def test_a_draft_nobody_has_touched_gets_no_sync_proposal(app_client):
    draft = make_draft(app_client)
    entry = make_entry(app_client, bullets=["Ran the rig"])
    drafts.place_entry(draft["id"], entry["id"])

    assert drafts.sync_proposal(draft["id"]) is None


def test_a_bullet_tailored_away_from_the_bank_is_not_reported_as_drift(app_client):
    """Drift is measured against the wording the bank had when the line was
    placed, not against the draft's own text. A deliberate rewrite is not stale.

    The second bullet is genuinely out of date, so a check that reported
    nothing at all would agree with this test for the wrong reason.
    """
    draft = make_draft(app_client)
    entry = make_entry(app_client, bullets=["Assisted with the rig", "Logged the runs"])
    drafts.place_entry(draft["id"], entry["id"])
    placement = only_placement(app_client, draft["id"])
    proposal_id = make_proposal(draft["id"], [{
        "op": "RewriteBullet", "placement_id": placement["ref"],
        "bullet_ref": placement["bullets"][0]["ref"],
        "bullet_id": entry["bullets"][0]["id"], "text": "Rebuilt the beamline rig",
    }])
    resolve(app_client, proposal_id)
    app_client.patch(f"/api/bank/bullets/{entry['bullets'][1]['id']}", json={"text": "Logged 40 runs"})

    standing = drafts.sync_proposal(draft["id"])

    assert [op["text"] for op in standing["operations"]] == ["Logged 40 runs"]


def test_accepting_a_drifted_bullet_stops_it_drifting_again(app_client):
    draft = make_draft(app_client)
    entry = make_entry(app_client, bullets=["Assisted with the rig"])
    drafts.place_entry(draft["id"], entry["id"])
    app_client.patch(f"/api/bank/bullets/{entry['bullets'][0]['id']}", json={"text": "Rebuilt the rig"})

    resolve(app_client, drafts.sync_proposal(draft["id"])["id"])

    assert only_placement(app_client, draft["id"])["bullets"][0]["text"] == "Rebuilt the rig"
    assert drafts.sync_proposal(draft["id"]) is None


def test_a_second_drift_check_replaces_the_standing_offer_rather_than_stacking_one(app_client):
    draft = make_draft(app_client)
    entry = make_entry(app_client, bullets=["Assisted with the rig"])
    drafts.place_entry(draft["id"], entry["id"])
    app_client.patch(f"/api/bank/bullets/{entry['bullets'][0]['id']}", json={"text": "Rebuilt the rig"})

    drafts.sync_proposal(draft["id"])
    drafts.sync_proposal(draft["id"])

    pending = [p for p in drafts.list_proposals(draft["id"]) if p["status"] == "pending"]
    assert len(pending) == 1


def test_undoing_the_bank_edit_withdraws_the_offer_to_sync(app_client):
    draft = make_draft(app_client)
    entry = make_entry(app_client, bullets=["Assisted with the rig"])
    drafts.place_entry(draft["id"], entry["id"])
    bullet_id = entry["bullets"][0]["id"]
    app_client.patch(f"/api/bank/bullets/{bullet_id}", json={"text": "Rebuilt the rig"})
    assert drafts.sync_proposal(draft["id"]) is not None

    app_client.patch(f"/api/bank/bullets/{bullet_id}", json={"text": "Assisted with the rig"})

    assert drafts.sync_proposal(draft["id"]) is None
    assert drafts.list_proposals(draft["id"]) == []


def test_reading_the_proposal_list_refreshes_the_drift_check(app_client):
    draft = make_draft(app_client)
    entry = make_entry(app_client, bullets=["Assisted with the rig"])
    drafts.place_entry(draft["id"], entry["id"])
    app_client.patch(f"/api/bank/bullets/{entry['bullets'][0]['id']}", json={"text": "Rebuilt the rig"})

    listed = app_client.get(f"/api/drafts/{draft['id']}/proposals").json()

    assert [proposal["kind"] for proposal in listed] == ["sync"]


def test_reading_the_list_twice_offers_the_same_proposal_both_times(app_client):
    """The drift check runs on read. Re-minting the row would hand the second
    reader a different id for an offer that has not changed."""
    draft = make_draft(app_client)
    entry = make_entry(app_client, bullets=["Assisted with the rig"])
    drafts.place_entry(draft["id"], entry["id"])
    app_client.patch(f"/api/bank/bullets/{entry['bullets'][0]['id']}", json={"text": "Rebuilt the rig"})

    first = app_client.get(f"/api/drafts/{draft['id']}/proposals").json()
    second = app_client.get(f"/api/drafts/{draft['id']}/proposals").json()

    assert [p["kind"] for p in first] == ["sync"]
    assert first == second


def test_an_offer_survives_the_read_that_follows_it(app_client):
    """The client lists, the user clicks apply, and the list refreshes
    underneath. The id they are holding has to still resolve."""
    draft = make_draft(app_client)
    entry = make_entry(app_client, bullets=["Assisted with the rig"])
    drafts.place_entry(draft["id"], entry["id"])
    app_client.patch(f"/api/bank/bullets/{entry['bullets'][0]['id']}", json={"text": "Rebuilt the rig"})
    proposal_id = app_client.get(f"/api/drafts/{draft['id']}/proposals").json()[0]["id"]

    app_client.get(f"/api/drafts/{draft['id']}/proposals")

    assert resolve(app_client, proposal_id).status_code == 200
    assert only_placement(app_client, draft["id"])["bullets"][0]["text"] == "Rebuilt the rig"


def test_a_changed_drift_set_replaces_the_standing_offer(app_client):
    """Stability is for an unchanged draft. An offer whose contents moved on is
    a different offer, and applying the old one would write stale text."""
    draft = make_draft(app_client)
    entry = make_entry(app_client, bullets=["Assisted with the rig"])
    drafts.place_entry(draft["id"], entry["id"])
    bullet_id = entry["bullets"][0]["id"]
    app_client.patch(f"/api/bank/bullets/{bullet_id}", json={"text": "Rebuilt the rig"})
    first = app_client.get(f"/api/drafts/{draft['id']}/proposals").json()[0]

    app_client.patch(f"/api/bank/bullets/{bullet_id}", json={"text": "Rebuilt the beamline rig"})
    second = app_client.get(f"/api/drafts/{draft['id']}/proposals").json()

    assert [p["id"] for p in second] != [first["id"]]
    assert [op["text"] for op in second[0]["operations"]] == ["Rebuilt the beamline rig"]


# ------------------------------------------------------------ the op algebra

def placed(client, bullets=("One", "Two")) -> tuple[dict, dict, dict]:
    draft = make_draft(client)
    entry = make_entry(client, bullets=list(bullets))
    drafts.place_entry(draft["id"], entry["id"])
    return draft, entry, only_placement(client, draft["id"])


def test_applying_only_the_accepted_operations_leaves_the_rest_undone(app_client):
    draft, _entry, placement = placed(app_client)
    proposal_id = make_proposal(draft["id"], [
        {"op": "DropBullet", "accepted": True, "placement_id": placement["ref"],
         "bullet_ref": placement["bullets"][0]["ref"]},
        {"op": "RenameSection", "accepted": False, "section_id": "unused",
         "label": "Research Experience"},
    ])

    assert resolve(app_client, proposal_id).status_code == 200

    body = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]
    assert [b["text"] for b in body["sections"][0]["placements"][0]["bullets"]] == ["Two"]
    assert body["sections"][0]["label"] == "Experience"


def test_the_accept_states_the_user_sent_beat_the_ones_the_proposal_was_stored_with(app_client):
    draft, _entry, placement = placed(app_client)
    proposal_id = make_proposal(draft["id"], [
        {"op": "DropBullet", "accepted": True, "placement_id": placement["ref"],
         "bullet_ref": placement["bullets"][0]["ref"]},
    ])

    resolve(app_client, proposal_id, operations=[
        {"op": "DropBullet", "accepted": False, "placement_id": placement["ref"],
         "bullet_ref": placement["bullets"][0]["ref"]},
    ])

    assert [b["text"] for b in only_placement(app_client, draft["id"])["bullets"]] == ["One", "Two"]


def test_an_operation_nobody_proposed_cannot_be_smuggled_into_a_resolve(app_client):
    """A resolve records a decision on what was offered. Taking the client's
    list wholesale made every proposal an open write channel into the draft."""
    draft, _entry, placement = placed(app_client)
    proposal_id = make_proposal(draft["id"], [
        {"op": "DropBullet", "placement_id": placement["ref"],
         "bullet_ref": placement["bullets"][0]["ref"]},
    ])

    response = resolve(app_client, proposal_id, operations=[
        {"op": "DropBullet", "placement_id": placement["ref"],
         "bullet_ref": placement["bullets"][1]["ref"]},
    ])

    assert response.status_code == 400, response.text
    assert [b["text"] for b in only_placement(app_client, draft["id"])["bullets"]] == ["One", "Two"]


def test_a_resolve_records_the_decision_without_rewriting_the_offer(app_client):
    """The stored proposal is the evidence of what the tailoring pass asked
    for. A resolve may say yes or no to each line and nothing else."""
    draft, _entry, placement = placed(app_client)
    proposal_id = make_proposal(draft["id"], [
        {"op": "DropBullet", "placement_id": placement["ref"],
         "bullet_ref": placement["bullets"][0]["ref"],
         "rationale": "The ad never mentions rigs"},
    ])

    resolve(app_client, proposal_id, operations=[
        {"op": "DropBullet", "accepted": False, "placement_id": placement["ref"],
         "bullet_ref": placement["bullets"][0]["ref"], "rationale": "I made this up"},
    ])

    stored = drafts.get_proposal(proposal_id)["operations"]
    assert [op["rationale"] for op in stored] == ["The ad never mentions rigs"]
    assert [op["accepted"] for op in stored] == [False]


def test_a_reviewed_set_that_is_not_the_offered_set_is_refused(app_client):
    """The answer is the offer with the boxes filled in. A short list is a
    client that lost track of what it was answering, not a set of rejections
    the server should guess at."""
    draft, _entry, placement = placed(app_client)
    proposal_id = make_proposal(draft["id"], [
        {"op": "DropBullet", "placement_id": placement["ref"],
         "bullet_ref": placement["bullets"][0]["ref"]},
        {"op": "DropBullet", "placement_id": placement["ref"],
         "bullet_ref": placement["bullets"][1]["ref"]},
    ])

    response = resolve(app_client, proposal_id, operations=[
        {"op": "DropBullet", "placement_id": placement["ref"],
         "bullet_ref": placement["bullets"][0]["ref"]},
    ])

    assert response.status_code == 400, response.text
    assert [b["text"] for b in only_placement(app_client, draft["id"])["bullets"]] == ["One", "Two"]


def test_two_identical_operations_take_their_own_answers(app_client):
    """Paired by position, because two operations that are identical cannot
    be told apart by content. Matching on content gave them both whichever
    answer arrived last, so a box the user unticked was applied anyway."""
    draft, entry, placement = placed(app_client, bullets=("One",))
    add = {"op": "AddBullet", "placement_id": placement["ref"],
           "bullet_id": entry["bullets"][0]["id"]}
    proposal_id = make_proposal(draft["id"], [dict(add), dict(add)])

    resolve(app_client, proposal_id,
            operations=[dict(add, accepted=True), dict(add, accepted=False)])

    assert [b["text"] for b in only_placement(app_client, draft["id"])["bullets"]] == ["One", "One"]
    assert [op["accepted"] for op in drafts.get_proposal(proposal_id)["operations"]] == [True, False]


@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_an_id_that_is_not_an_integer_is_refused_rather_than_rounded(app_client, value):
    """Pydantic's default coercion reads all three of these as the integer 1,
    so a malformed request silently named bank record 1 and was applied. The
    model the agent writes through already refused them, so the two gates
    disagreed and the lax one was the public route."""
    draft, entry, placement = placed(app_client)
    proposal_id = make_proposal(draft["id"], [
        {"op": "AddBullet", "placement_id": placement["ref"],
         "bullet_id": entry["bullets"][0]["id"]},
    ])

    response = resolve(app_client, proposal_id, operations=[
        {"op": "AddBullet", "placement_id": placement["ref"], "bullet_id": value},
    ])

    assert response.status_code == 422, response.text
    assert [b["text"] for b in only_placement(app_client, draft["id"])["bullets"]] == ["One", "Two"]



def test_applying_the_same_proposal_twice_changes_nothing_the_second_time(app_client):
    """A retry, a double click or a replayed request must not drop two bullets."""
    draft, _entry, placement = placed(app_client, bullets=("One", "Two", "Three"))
    proposal_id = make_proposal(draft["id"], [
        {"op": "DropBullet", "placement_id": placement["ref"],
         "bullet_ref": placement["bullets"][0]["ref"]},
    ])

    first = resolve(app_client, proposal_id).json()
    second = resolve(app_client, proposal_id).json()

    assert [b["text"] for b in first["body"]["sections"][0]["placements"][0]["bullets"]] == ["Two", "Three"]
    assert second["body"] == first["body"]


def test_whoever_resolves_a_proposal_first_decides_what_it_did(app_client, monkeypatch):
    """Routes are sync `def`, so two clicks on Apply genuinely run at once. The
    status check happens before the new body is computed, so the request that
    arrives second is still mid-flight when the first one finishes. Here the
    first declines the operation and the second accepts it; the second must
    lose rather than overwrite the decision that already landed."""
    draft, _entry, placement = placed(app_client, bullets=("One", "Two", "Three"))
    operation = {"op": "DropBullet", "placement_id": placement["ref"],
                 "bullet_ref": placement["bullets"][0]["ref"]}
    proposal_id = make_proposal(draft["id"], [operation])
    real_check = drafts._check_bank_refs
    reentered = []

    def another_request_gets_there_first(accepted, index):
        if not reentered:
            reentered.append(1)
            drafts.apply_proposal(proposal_id, [dict(operation, accepted=False)])
        return real_check(accepted, index)

    monkeypatch.setattr(drafts, "_check_bank_refs", another_request_gets_there_first)
    drafts.apply_proposal(proposal_id)

    assert [b["text"] for b in only_placement(app_client, draft["id"])["bullets"]] == [
        "One", "Two", "Three"
    ]


def test_an_edit_that_lands_mid_apply_is_kept(app_client, monkeypatch):
    """Routes are sync `def`, so the user can save the canvas while an apply is
    in flight. The apply read the body at the start and stored it at the end,
    so a save that landed in between vanished with no error anywhere."""
    draft, _entry, placement = placed(app_client, bullets=("One", "Two"))
    operation = {"op": "DropBullet", "placement_id": placement["ref"],
                 "bullet_ref": placement["bullets"][0]["ref"]}
    proposal_id = make_proposal(draft["id"], [operation])
    real_check = drafts._check_bank_refs
    saved = []

    def the_user_saves_the_canvas_meanwhile(accepted, index):
        if not saved:
            saved.append(1)
            body = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]
            body["sections"][0]["label"] = "Research Experience"
            app_client.patch(f"/api/drafts/{draft['id']}", json={"body": body})
        return real_check(accepted, index)

    monkeypatch.setattr(drafts, "_check_bank_refs", the_user_saves_the_canvas_meanwhile)
    drafts.apply_proposal(proposal_id)

    section = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]["sections"][0]
    assert section["label"] == "Research Experience"
    assert [b["text"] for b in section["placements"][0]["bullets"]] == ["Two"]


def test_an_applied_proposal_is_marked_applied_and_stops_being_pending(app_client):
    draft, _entry, placement = placed(app_client)
    proposal_id = make_proposal(draft["id"], [
        {"op": "MoveBullet", "placement_id": placement["ref"],
         "bullet_ref": placement["bullets"][1]["ref"], "position": 0},
    ])

    resolve(app_client, proposal_id)

    proposal = drafts.get_proposal(proposal_id)
    assert proposal["status"] == "applied"
    assert proposal["resolved_at"] is not None


def test_a_dismissed_proposal_never_reaches_the_draft(app_client):
    draft, _entry, placement = placed(app_client)
    proposal_id = make_proposal(draft["id"], [
        {"op": "DropBullet", "placement_id": placement["ref"],
         "bullet_ref": placement["bullets"][0]["ref"]},
    ])

    app_client.post(f"/api/proposals/{proposal_id}/resolve", json={"action": "dismiss"})
    resolve(app_client, proposal_id)

    assert [b["text"] for b in only_placement(app_client, draft["id"])["bullets"]] == ["One", "Two"]
    assert drafts.get_proposal(proposal_id)["status"] == "dismissed"


def test_an_operation_naming_a_bullet_the_bank_no_longer_holds_is_refused(app_client):
    """The closed algebra, enforced. An operation may only reach for records
    that already exist, which is what stops a tailoring pass inventing them."""
    draft, entry, placement = placed(app_client)
    bullet_id = entry["bullets"][0]["id"]
    app_client.delete(f"/api/bank/bullets/{bullet_id}")
    proposal_id = make_proposal(draft["id"], [
        {"op": "AddBullet", "placement_id": placement["ref"], "bullet_id": bullet_id},
    ])

    response = resolve(app_client, proposal_id)

    assert response.status_code == 400
    assert "not in the bank" in response.json()["detail"]


def test_an_operation_naming_an_entry_the_bank_does_not_hold_is_refused(app_client):
    draft = make_draft(app_client)
    proposal_id = make_proposal(draft["id"], [{"op": "AddEntry", "entry_id": 9999}])

    response = resolve(app_client, proposal_id)

    assert response.status_code == 400
    assert "not in the bank" in response.json()["detail"]


def test_an_add_entry_operation_that_names_no_entry_at_all_is_refused(app_client):
    draft = make_draft(app_client)
    proposal_id = make_proposal(draft["id"], [{"op": "AddEntry", "section": "Experience"}])

    assert resolve(app_client, proposal_id).status_code == 400


def test_a_bullet_cannot_be_added_under_a_record_it_does_not_belong_to(app_client):
    """The closed algebra is what stops a tailoring pass inventing experience.
    Hanging one employer's achievement under another is exactly that, and it
    sticks: the snapshot anchors to the foreign bullet, so editing that bullet
    in the bank writes the misattribution back in."""
    draft, _entry, placement = placed(app_client, bullets=("Ran the rig",))
    elsewhere = make_entry(app_client, title="Barista", organization="Cafe",
                           bullets=["Shipped a compiler"])
    proposal_id = make_proposal(draft["id"], [{
        "op": "AddBullet", "placement_id": placement["ref"],
        "bullet_id": elsewhere["bullets"][0]["id"],
    }])

    response = resolve(app_client, proposal_id)

    assert response.status_code == 400, response.text
    assert [b["text"] for b in only_placement(app_client, draft["id"])["bullets"]] == ["Ran the rig"]


def test_a_bullet_from_the_records_own_entry_is_added(app_client):
    """The other side of the same check: a bullet the user wrote under this
    record, dropped from the draft and offered back, still goes in."""
    draft, entry, placement = placed(app_client, bullets=("One", "Two"))
    body = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]
    body["sections"][0]["placements"][0]["bullets"] = []
    app_client.patch(f"/api/drafts/{draft['id']}", json={"body": body})
    proposal_id = make_proposal(draft["id"], [{
        "op": "AddBullet", "placement_id": placement["ref"],
        "bullet_id": entry["bullets"][1]["id"],
    }])

    assert resolve(app_client, proposal_id).status_code == 200
    assert [b["text"] for b in only_placement(app_client, draft["id"])["bullets"]] == ["Two"]


def test_an_operation_naming_a_line_that_is_not_in_the_draft_is_refused(app_client):
    draft, _entry, placement = placed(app_client)
    proposal_id = make_proposal(draft["id"], [
        {"op": "RewriteBullet", "placement_id": placement["ref"],
         "bullet_ref": "nothing-like-this", "text": "Rebuilt the rig"},
    ])

    response = resolve(app_client, proposal_id)

    assert response.status_code == 400
    assert "no bullet" in response.json()["detail"]


def test_one_refused_operation_leaves_the_whole_draft_untouched(app_client):
    """Half-applying a proposal would leave a resume nobody chose, with no
    record of which operations landed."""
    draft, _entry, placement = placed(app_client)
    proposal_id = make_proposal(draft["id"], [
        {"op": "DropBullet", "placement_id": placement["ref"],
         "bullet_ref": placement["bullets"][0]["ref"]},
        {"op": "DropBullet", "placement_id": placement["ref"], "bullet_ref": "gone"},
    ])

    assert resolve(app_client, proposal_id).status_code == 400

    assert [b["text"] for b in only_placement(app_client, draft["id"])["bullets"]] == ["One", "Two"]
    assert drafts.get_proposal(proposal_id)["status"] == "pending"


def test_an_operation_outside_the_algebra_is_refused(app_client):
    draft = make_draft(app_client)
    proposal_id = make_proposal(draft["id"], [{"op": "DeleteEverything"}])

    response = resolve(app_client, proposal_id)

    assert response.status_code == 400
    assert "not an operation" in response.json()["detail"]


def test_add_entry_snapshots_the_record_the_same_way_a_drag_would(app_client):
    draft = make_draft(app_client)
    entry = make_entry(app_client, bullets=["Ran the rig"])
    proposal_id = make_proposal(draft["id"], [{"op": "AddEntry", "entry_id": entry["id"]}])

    resolve(app_client, proposal_id)

    placement = only_placement(app_client, draft["id"])
    assert placement["title"] == "Lab assistant"
    assert placement["dates"] == "Jun 2026 – Sep 2026"
    assert placement["bullets"][0]["source_bullet_id"] == entry["bullets"][0]["id"]


def test_a_section_can_be_renamed_for_the_job_it_is_aimed_at(app_client):
    draft, _entry, _placement = placed(app_client)
    section_ref = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]["sections"][0]["ref"]
    proposal_id = make_proposal(draft["id"], [
        {"op": "RenameSection", "section_id": section_ref, "label": "Research Experience"},
    ])

    resolve(app_client, proposal_id)

    body = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]
    assert body["sections"][0]["label"] == "Research Experience"


def test_dropping_an_entry_removes_it_from_the_page(app_client):
    draft, _entry, placement = placed(app_client)
    proposal_id = make_proposal(draft["id"], [
        {"op": "DropEntry", "placement_id": placement["ref"]},
    ])

    resolve(app_client, proposal_id)

    body = app_client.get(f"/api/drafts/{draft['id']}").json()["body"]
    assert body["sections"][0]["placements"] == []


def test_a_rewritten_bullet_stays_anchored_to_the_record_it_came_from(app_client):
    """`RewriteBullet` changes wording only. Cutting the anchor would make the
    line unattributable and invisible to every later drift check."""
    draft, entry, placement = placed(app_client, bullets=("Assisted with the rig",))
    proposal_id = make_proposal(draft["id"], [
        {"op": "RewriteBullet", "placement_id": placement["ref"],
         "bullet_ref": placement["bullets"][0]["ref"], "text": "Rebuilt the beamline rig"},
    ])

    resolve(app_client, proposal_id)

    bullet = only_placement(app_client, draft["id"])["bullets"][0]
    assert bullet["text"] == "Rebuilt the beamline rig"
    assert bullet["source_bullet_id"] == entry["bullets"][0]["id"]


def test_a_tailored_rewrite_leaves_unreviewed_drift_standing(app_client):
    """A tailoring pass rewrites for the job it is aimed at. It has not shown
    the user what the bank now says, so re-anchoring to it would withdraw a
    decision they were owed and never saw."""
    draft, entry, placement = placed(app_client, bullets=("Assisted with the rig",))
    bullet_id = entry["bullets"][0]["id"]
    app_client.patch(f"/api/bank/bullets/{bullet_id}", json={"text": "Rebuilt the rig"})
    proposal_id = make_proposal(draft["id"], [
        {"op": "RewriteBullet", "placement_id": placement["ref"],
         "bullet_ref": placement["bullets"][0]["ref"], "bullet_id": bullet_id,
         "text": "Rebuilt the beamline rig for the ACME run"},
    ])

    resolve(app_client, proposal_id)

    standing = drafts.sync_proposal(draft["id"])
    assert standing is not None, "the drift the user never saw went away on its own"
    assert [op["text"] for op in standing["operations"]] == ["Rebuilt the rig"]


# ------------------------------------------------------------------ rendering

def test_the_latex_preview_never_writes_anything(app_client):
    draft, _entry, _placement = placed(app_client)
    before = app_client.get(f"/api/drafts/{draft['id']}").json()

    preview = app_client.get(f"/api/drafts/{draft['id']}/latex").json()

    assert preview["pushed"] is False
    assert preview["pushed_latex"] is None
    assert app_client.get(f"/api/drafts/{draft['id']}").json() == before


def test_the_preview_puts_the_draft_inside_the_users_own_template(app_client):
    draft, _entry, _placement = placed(app_client, bullets=("Ran the rig",))

    latex = app_client.get(f"/api/drafts/{draft['id']}/latex").json()["latex"]

    assert latex.startswith(r"\documentclass")
    assert "%%RESUME-BODY%%" not in latex
    assert r"\resumeItem{Ran the rig}" in latex


def test_a_template_with_no_body_marker_is_a_400_rather_than_a_crash(app_client):
    draft, _entry, _placement = placed(app_client)
    database.set_setting("resume_template", r"\documentclass{article}")

    response = app_client.get(f"/api/drafts/{draft['id']}/latex")

    assert response.status_code == 400
    assert "%%RESUME-BODY%%" in response.json()["detail"]


def test_a_draft_whose_bank_entry_was_deleted_still_renders(app_client):
    """The snapshot is the document. Losing the record behind it must not cost
    the user a resume they already composed."""
    draft, entry, _placement = placed(app_client, bullets=("Ran the rig",))

    assert app_client.delete(f"/api/bank/entries/{entry['id']}").status_code == 204

    latex = app_client.get(f"/api/drafts/{draft['id']}/latex").json()["latex"]
    assert r"\resumeItem{Ran the rig}" in latex
    assert r"\resumeSubheading{Argonne}" in latex


# ----------------------------------------------------------------------- push

def test_push_writes_the_render_into_the_variant_and_remembers_what_it_wrote(
    app_client, resume_tmp
):
    instance = resumes.create_instance("Target", latex_source="")
    draft, _entry, _placement = placed(app_client, bullets=("Ran the rig",))
    app_client.patch(f"/api/drafts/{draft['id']}", json={"resume_instance_id": instance["id"]})

    result = app_client.post(f"/api/drafts/{draft['id']}/push").json()

    assert result["pushed"] is True
    assert r"\resumeItem{Ran the rig}" in result["latex"]
    assert resumes.get_instance(instance["id"])["latex"] == result["latex"]
    assert app_client.get(f"/api/drafts/{draft['id']}").json()["pushed_latex"] == result["latex"]


def test_a_draft_with_no_variant_behind_it_gets_one_on_its_first_push(app_client, resume_tmp):
    draft, _entry, _placement = placed(app_client, bullets=("Ran the rig",))

    result = app_client.post(f"/api/drafts/{draft['id']}/push").json()

    assert result["resume_instance_id"] is not None
    assert resumes.get_instance(result["resume_instance_id"])["latex"] == result["latex"]


def test_pushing_twice_with_no_edit_in_between_is_allowed(app_client, resume_tmp):
    draft, _entry, _placement = placed(app_client, bullets=("Ran the rig",))
    first = app_client.post(f"/api/drafts/{draft['id']}/push").json()

    second = app_client.post(f"/api/drafts/{draft['id']}/push")

    assert second.status_code == 200
    assert second.json()["latex"] == first["latex"]


def test_pushing_over_a_hand_edit_is_refused_and_hands_back_both_texts(app_client, resume_tmp):
    """`pushed_latex` is exactly what the last push wrote, so anything else in
    the variant is the user's own work and overwriting it would lose it."""
    draft, _entry, _placement = placed(app_client, bullets=("Ran the rig",))
    pushed = app_client.post(f"/api/drafts/{draft['id']}/push").json()
    instance_id = pushed["resume_instance_id"]
    resumes.update_instance(instance_id, {"latex": "% I rewrote this by hand"})

    response = app_client.post(f"/api/drafts/{draft['id']}/push")

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["current_latex"] == "% I rewrote this by hand"
    assert detail["pushed_latex"] == pushed["latex"]
    assert detail["diverged"] is True
    assert resumes.get_instance(instance_id)["latex"] == "% I rewrote this by hand"


def test_a_forced_push_overwrites_the_hand_edit(app_client, resume_tmp):
    draft, _entry, _placement = placed(app_client, bullets=("Ran the rig",))
    instance_id = app_client.post(f"/api/drafts/{draft['id']}/push").json()["resume_instance_id"]
    resumes.update_instance(instance_id, {"latex": "% I rewrote this by hand"})

    forced = app_client.post(f"/api/drafts/{draft['id']}/push?force=true")

    assert forced.status_code == 200
    assert resumes.get_instance(instance_id)["latex"] == forced.json()["latex"]


def test_the_preview_reports_a_hand_edit_without_refusing_anything(app_client, resume_tmp):
    draft, _entry, _placement = placed(app_client, bullets=("Ran the rig",))
    instance_id = app_client.post(f"/api/drafts/{draft['id']}/push").json()["resume_instance_id"]
    resumes.update_instance(instance_id, {"latex": "% I rewrote this by hand"})

    preview = app_client.get(f"/api/drafts/{draft['id']}/latex").json()

    assert preview["diverged"] is True
    assert preview["pushed"] is False


def test_an_untouched_variant_does_not_read_as_diverged(app_client, resume_tmp):
    draft, _entry, _placement = placed(app_client, bullets=("Ran the rig",))
    app_client.post(f"/api/drafts/{draft['id']}/push")

    assert app_client.get(f"/api/drafts/{draft['id']}/latex").json()["diverged"] is False


def test_pushing_after_the_variant_was_deleted_starts_exactly_one_fresh_one(
    app_client, resume_tmp
):
    """A variant that is gone is not a hand edit. `pushed_latex` then describes
    a row nobody can lose work from, so refusing protects nothing, and every
    refused retry minted another empty variant on its way to saying no."""
    draft, _entry, _placement = placed(app_client, bullets=("Ran the rig",))
    first = app_client.post(f"/api/drafts/{draft['id']}/push").json()
    resumes.delete_instance(first["resume_instance_id"])
    before = len(resumes.list_instances())

    for _ in range(3):
        again = app_client.post(f"/api/drafts/{draft['id']}/push")
        assert again.status_code == 200, again.text

    assert len(resumes.list_instances()) == before + 1
    replacement = again.json()["resume_instance_id"]
    assert replacement != first["resume_instance_id"]
    assert resumes.get_instance(replacement)["latex"] == again.json()["latex"]
    assert app_client.get(f"/api/drafts/{draft['id']}").json()["resume_instance_id"] == replacement


def test_a_push_that_would_change_nothing_is_not_a_conflict(app_client, resume_tmp):
    """Refusing protects work a push would discard. A variant that already
    holds exactly what the draft renders has no such work in it."""
    draft, _entry, _placement = placed(app_client, bullets=("Ran the rig",))
    rendered = app_client.get(f"/api/drafts/{draft['id']}/latex").json()["latex"]
    instance = resumes.create_instance("Target", latex_source=rendered)
    app_client.patch(f"/api/drafts/{draft['id']}", json={"resume_instance_id": instance["id"]})

    response = app_client.post(f"/api/drafts/{draft['id']}/push")

    assert response.status_code == 200, response.text
    assert response.json()["latex"] == rendered


# ------------------------------------------------------------------- coverage

def job_post(keywords: list[dict]) -> int:
    with database.get_db() as conn:
        cursor = conn.execute(
            "INSERT INTO job_posts (title, raw_text, keywords) VALUES ('Intern', 'the ad', ?)",
            (json.dumps(keywords),),
        )
        return int(cursor.lastrowid)


def test_a_draft_with_no_job_post_behind_it_reports_nothing_to_cover(app_client):
    draft, _entry, _placement = placed(app_client)

    report = app_client.get(f"/api/drafts/{draft['id']}/coverage").json()

    assert report == {"draft_id": draft["id"], "job_post_id": None,
                      "covered": 0, "total": 0, "keywords": []}


def test_coverage_counts_the_terms_the_draft_actually_says(app_client):
    post_id = job_post([{"term": "PyTorch"}, {"term": "Fortran"}])
    draft = make_draft(app_client, job_post_id=post_id)
    entry = make_entry(app_client, bullets=["Trained a PyTorch model"])
    drafts.place_entry(draft["id"], entry["id"])

    report = app_client.get(f"/api/drafts/{draft['id']}/coverage").json()

    assert report["total"] == 2
    assert report["covered"] == 1
    assert [term["term"] for term in report["keywords"] if term["covered"]] == ["PyTorch"]


def test_coverage_points_at_the_entry_carrying_each_term(app_client):
    post_id = job_post([{"term": "PyTorch"}])
    draft = make_draft(app_client, job_post_id=post_id)
    entry = make_entry(app_client, bullets=["Trained a PyTorch model"])
    drafts.place_entry(draft["id"], entry["id"])

    report = app_client.get(f"/api/drafts/{draft['id']}/coverage").json()

    assert report["keywords"][0]["where"] == [only_placement(app_client, draft["id"])["ref"]]


def test_a_term_buried_inside_a_longer_word_does_not_count_as_covered(app_client):
    """The report runs the real matcher, which compares whole folded tokens.
    A substring check would read \"Collaborated\" as another mention of Lab and
    tell the user they had said it twice."""
    post_id = job_post([{"term": "Lab"}])
    draft = make_draft(app_client, job_post_id=post_id)
    entry = make_entry(app_client, title="Lab assistant", bullets=["Collaborated on the rig"])
    drafts.place_entry(draft["id"], entry["id"])

    report = app_client.get(f"/api/drafts/{draft['id']}/coverage").json()

    assert report["keywords"][0]["hits"] == 1


def test_a_term_hiding_in_a_repo_url_does_not_count_as_covered(app_client):
    """A project linking to github.com/me/pytorch-oracle would otherwise claim
    PyTorch, which is the report telling the user the resume says something it
    does not say."""
    post_id = job_post([{"term": "PyTorch"}])
    draft = make_draft(app_client, job_post_id=post_id)
    entry = make_entry(app_client, kind="project", title="Oracle", detail="Rust",
                       url="https://github.com/me/pytorch-oracle", bullets=["Shipped it"])
    drafts.place_entry(draft["id"], entry["id"])

    report = app_client.get(f"/api/drafts/{draft['id']}/coverage").json()

    assert [term["covered"] for term in report["keywords"]] == [False]
    assert report["covered"] == 0


def test_a_segment_carries_the_entrys_own_words_and_its_bullets():
    body = {"sections": [{"ref": "s", "label": "Experience", "placements": [
        {"ref": "p", "kind": "experience", "title": "Lab assistant",
         "organization": "Argonne", "detail": None,
         "bullets": [{"ref": "b", "text": "Ran the rig"}]},
    ]}]}

    assert drafts.draft_segments(body) == [("p", "Lab assistant Argonne Ran the rig")]


# ------------------------------------------------ the bridge back to Resumes

def test_a_resume_says_which_draft_composed_it(app_client):
    """Resumes could not tell a composed version from a typed one, so it had
    no way to offer a way back to the canvas that produced it."""
    typed = app_client.post("/api/resumes", json={"name": "Typed by hand"}).json()
    draft = make_draft(app_client, name="Composed")
    app_client.post(f"/api/drafts/{draft['id']}/push")

    rows = {row["name"]: row for row in app_client.get("/api/resumes").json()}

    assert rows["Typed by hand"]["draft_id"] is None
    assert rows["Composed"]["draft_id"] == draft["id"]


def test_renaming_a_pushed_draft_renames_the_resume_it_became(app_client):
    """While they are linked they are one thing. The resume used to keep
    whatever the draft was called at the moment it was first pushed."""
    draft = make_draft(app_client, name="New resume")
    instance_id = app_client.post(f"/api/drafts/{draft['id']}/push").json()["resume_instance_id"]

    app_client.patch(f"/api/drafts/{draft['id']}", json={"name": "Backend Intern, Fermilab"})

    assert app_client.get(f"/api/resumes/{instance_id}").json()["name"] == "Backend Intern, Fermilab"


def test_renaming_a_draft_that_was_never_pushed_touches_no_resume(app_client):
    draft = make_draft(app_client, name="Never pushed")

    app_client.patch(f"/api/drafts/{draft['id']}", json={"name": "Still not pushed"})

    assert app_client.get("/api/resumes").json() == []
