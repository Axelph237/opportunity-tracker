"""Resume drafts: composing them, proposing changes to them, pushing them out.

A draft is a *snapshot*, not a view. Placing a bank entry copies its text into
the draft and records where that text came from. A later bank edit therefore
cannot change a resume the user has already sent; it shows up as drift the user
is offered the chance to accept.

Every change a draft receives from something other than the user's own hands
arrives as a `Proposal`: a list of operations from a closed algebra, each
independently acceptable. The algebra is the point. There is no operation that
introduces a record, only ones that place, move, drop or reword records already
in the bank, and `_check_bank_refs` refuses any operation naming an id the bank
does not hold. That is what stops a tailoring pass inventing experience the
student does not have, and it is enforced here rather than asked for in a
prompt.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Optional
from uuid import uuid4

import bank
import jobposts
import keywords
import resume_render
import resumes
from bank import KindLayout
from database import get_db, get_setting

logger = logging.getLogger(__name__)

MAX_NAME_LENGTH = 120


class DraftNotFound(LookupError):
    """Raised when a draft or proposal id does not exist."""


class CorruptDraft(RuntimeError):
    """Raised when a stored JSON column is not the shape the column promises.

    Reading it as an empty value instead is how a corrupt row becomes a push
    that writes an empty resume over the user's variant and reports success,
    and how a proposal's record of what it offered becomes an empty list.
    """


class PushConflict(RuntimeError):
    """Raised when the linked resume no longer matches what we last wrote to it.

    Carries both texts so the caller can show the user the work it is refusing
    over, rather than a dialog asking them to guess what changed.
    """

    def __init__(self, draft_id: int, instance_id: Optional[int],
                 rendered: str, current: str, pushed: str) -> None:
        super().__init__(
            "This resume has been edited by hand since the draft last wrote to it. "
            "Pushing would discard those edits."
        )
        self.draft_id = draft_id
        self.resume_instance_id = instance_id
        self.rendered = rendered
        self.current = current
        self.pushed = pushed


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _new_ref() -> str:
    return uuid4().hex


def _json_value(value: Any, fallback: Any) -> Any:
    if not value:
        return deepcopy(fallback)
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError) as exc:
        raise CorruptDraft(f"Stored JSON will not parse: {exc}") from exc
    if not isinstance(parsed, type(fallback)):
        raise CorruptDraft(
            f"Stored JSON is a {type(parsed).__name__}, not a {type(fallback).__name__}."
        )
    return parsed


def _complete(body: Optional[dict]) -> dict:
    """A body the rest of this module can trust, whatever shape it arrived in."""
    body = body if isinstance(body, dict) else {}
    body.setdefault("sections", [])
    for section in body["sections"]:
        # A body stored or posted without a key takes the label it was created
        # under, which is what its key would have been.
        if not section.get("key"):
            section["key"] = section.get("label") or ""
    return body


def draft_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["body"] = _complete(_json_value(data.get("body"), {"sections": []}))
    return data


def proposal_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["operations"] = _json_value(data.get("operations"), [])
    return data


# --------------------------------------------------------------- body walking

def _sections(body: dict) -> list[dict]:
    return (body or {}).get("sections") or []


def _placements(body: dict) -> Iterator[tuple[dict, dict]]:
    for section in _sections(body):
        for placement in section.get("placements") or []:
            yield section, placement


def _locate_section(body: dict, ref: Optional[str]) -> dict:
    for section in _sections(body):
        if section.get("ref") == ref:
            return section
    raise ValueError(f"This draft has no section {ref!r}.")


def _locate_placement(body: dict, ref: Optional[str]) -> tuple[dict, dict]:
    for section, placement in _placements(body):
        if placement.get("ref") == ref:
            return section, placement
    raise ValueError(f"This draft has no entry {ref!r}.")


def _locate_bullet(placement: dict, ref: Optional[str]) -> dict:
    for bullet in placement.get("bullets") or []:
        if bullet.get("ref") == ref:
            return bullet
    raise ValueError(f"That entry has no bullet {ref!r}.")


def _insert(items: list, item: Any, position: Optional[int]) -> None:
    items.insert(len(items) if position is None else max(0, min(position, len(items))), item)


def _ensure_refs(body: dict) -> dict:
    """Give everything in a body a ref that is unique within the draft.

    Every operation addresses placements and bullets by ref, so a client that
    posted a body with a missing or repeated one would make those rows
    unaddressable, and a proposal would silently act on the wrong line.
    """
    body = _complete(body)
    seen: set[str] = set()

    def fresh(node: dict) -> None:
        ref = node.get("ref")
        if not ref or ref in seen:
            ref = _new_ref()
        node["ref"] = ref
        seen.add(ref)

    for section in _sections(body):
        fresh(section)
        for placement in section.get("placements") or []:
            fresh(placement)
            for bullet in placement.get("bullets") or []:
                fresh(bullet)
    return body


# ------------------------------------------------------------------ snapshots

def _snapshot_bullet(source: dict) -> dict[str, Any]:
    text = source.get("text") or ""
    return {
        "ref": _new_ref(),
        "text": text,
        "source_bullet_id": source.get("id"),
        "source_text": text,
    }


def _snapshot(entry: dict) -> dict[str, Any]:
    """Copy a bank record into the draft, with a trail back to where it came from.

    The dates are printed here rather than at render time: a draft shows what
    it showed, and a value recomputed on every render would change with no
    write to the draft to explain it.
    """
    return {
        "ref": _new_ref(),
        "entry_id": entry.get("id"),
        "kind": entry.get("kind"),
        "title": entry.get("title") or "",
        "organization": entry.get("organization"),
        "location": entry.get("location"),
        "dates": bank.format_dates(entry),
        "detail": entry.get("detail"),
        "url": entry.get("url"),
        "bullets": [_snapshot_bullet(bullet) for bullet in entry.get("bullets") or []],
    }


def _section_for(body: dict, key: str, layout: KindLayout) -> dict:
    for section in _sections(body):
        if section.get("key") == key:
            return section
    section = {"ref": _new_ref(), "key": key, "label": key,
               "bullet_style": layout.bullet_style, "placements": []}
    body.setdefault("sections", []).append(section)
    return section


# ----------------------------------------------------------------- draft CRUD

# The links a draft carries, and what to call the row on the other end. SQLite
# enforces these too, but its IntegrityError names no field and reaches the
# client as a 500, so the check lives here where the answer can say which link
# is wrong.
_LINKS = {
    "job_post_id": ("job_posts", "job post"),
    "resume_instance_id": ("resume_instances", "resume"),
}


def _check_links(conn: sqlite3.Connection, values: dict[str, Any]) -> None:
    for field, (table, noun) in _LINKS.items():
        target = values.get(field)
        if target is None:
            continue
        if conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (target,)).fetchone() is None:
            raise ValueError(f"There is no {noun} {target} to attach this draft to.")


def list_drafts() -> list[dict[str, Any]]:
    """Every draft, as the picker that chooses between them needs it.

    A row whose body will not parse is listed with an empty one rather than
    taking the whole collection down. Nothing here can overwrite anything:
    every path that writes a draft reads its body again, strictly, under its
    own lock. Losing the list would leave the healthy drafts intact and
    unreachable, because reaching them goes through it.
    """
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM resume_drafts ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    listed = []
    for row in rows:
        try:
            listed.append(draft_dict(row))
        except CorruptDraft as exc:
            logger.warning("Draft %s has an unreadable body: %s", row["id"], exc)
            listed.append({**dict(row), "body": {"sections": []}})
    return listed


def get_draft(draft_id: int) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM resume_drafts WHERE id = ?", (draft_id,)).fetchone()
    if row is None:
        raise DraftNotFound(f"Draft {draft_id} not found")
    return draft_dict(row)


def create_draft(
    name: str = "New draft",
    *,
    job_post_id: Optional[int] = None,
    resume_instance_id: Optional[int] = None,
) -> dict[str, Any]:
    clean = (name or "").strip()[:MAX_NAME_LENGTH] or "New draft"
    with get_db() as conn:
        _check_links(conn, {"job_post_id": job_post_id,
                            "resume_instance_id": resume_instance_id})
        cursor = conn.execute(
            """INSERT INTO resume_drafts (name, job_post_id, resume_instance_id, body, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (clean, job_post_id, resume_instance_id, json.dumps({"sections": []}), _now(), _now()),
        )
        draft_id = int(cursor.lastrowid)
    return get_draft(draft_id)


EDITABLE_FIELDS = ("name", "job_post_id", "resume_instance_id", "body")


def update_draft(draft_id: int, values: dict[str, Any]) -> dict[str, Any]:
    changes = {key: value for key, value in values.items() if key in EDITABLE_FIELDS}
    if "name" in changes:
        clean = (changes["name"] or "").strip()[:MAX_NAME_LENGTH]
        if not clean:
            raise ValueError("A draft needs a name.")
        changes["name"] = clean
    if "body" in changes:
        changes["body"] = json.dumps(_ensure_refs(changes["body"] or {"sections": []}))
    if not changes:
        return get_draft(draft_id)
    with get_db() as conn:
        if conn.execute("SELECT 1 FROM resume_drafts WHERE id = ?", (draft_id,)).fetchone() is None:
            raise DraftNotFound(f"Draft {draft_id} not found")
        _check_links(conn, changes)
        assignments = ", ".join(f"{column} = ?" for column in changes)
        conn.execute(
            f"UPDATE resume_drafts SET {assignments}, updated_at = ? WHERE id = ?",
            [*changes.values(), _now(), draft_id],
        )
    return get_draft(draft_id)


def delete_draft(draft_id: int) -> None:
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM resume_drafts WHERE id = ?", (draft_id,))
        if cursor.rowcount == 0:
            raise DraftNotFound(f"Draft {draft_id} not found")


def _mutate_body(conn: sqlite3.Connection, draft_id: int, change: Callable[[dict], None]) -> None:
    """Read, change and store a draft body without leaving the transaction.

    The read has to happen under the caller's write lock. Reading the body at
    the start of a request and storing it at the end let an edit that landed
    in between disappear, with nothing anywhere saying so. The change runs
    against the in-memory body and is stored once, so an operation that fails
    half way through rolls the whole request back rather than leaving a draft
    partly rewritten.
    """
    row = conn.execute("SELECT body FROM resume_drafts WHERE id = ?", (draft_id,)).fetchone()
    if row is None:
        raise DraftNotFound(f"Draft {draft_id} not found")
    body = _complete(_json_value(row["body"], {"sections": []}))
    change(body)
    conn.execute(
        "UPDATE resume_drafts SET body = ?, updated_at = ? WHERE id = ?",
        (json.dumps(body), _now(), draft_id),
    )


def place_entry(draft_id: int, entry_id: int, *, section_ref: Optional[str] = None) -> dict[str, Any]:
    """Snapshot a bank record into a draft."""
    # `bank.get_entry` opens its own connection, so it resolves before the
    # write below opens one.
    entry = bank.get_entry(entry_id)
    layout = bank.layout_for(entry.get("kind"))
    snapshot = _snapshot(entry)

    def place(body: dict) -> None:
        section = (
            _locate_section(body, section_ref) if section_ref
            else _section_for(body, layout.default_section, layout)
        )
        section.setdefault("placements", []).append(snapshot)

    with get_db() as conn:
        _mutate_body(conn, draft_id, place)
    return get_draft(draft_id)


# ------------------------------------------------------------ the op algebra

def _bank_index(conn: sqlite3.Connection) -> dict[str, dict[int, dict[str, Any]]]:
    """Every id the algebra is allowed to name, read in one go.

    Read through the caller's connection rather than via `bank.get_entry`,
    which opens its own: nesting a fresh connection inside an open write is
    how this project's deadlocks start.
    """
    bullets = [dict(row) for row in conn.execute(
        "SELECT * FROM bank_bullets ORDER BY entry_id, position, id"
    )]
    entries: dict[int, dict[str, Any]] = {}
    for row in conn.execute("SELECT * FROM bank_entries"):
        entry = bank.entry_dict(row)
        entry["bullets"] = [b for b in bullets if b["entry_id"] == row["id"]]
        entries[row["id"]] = entry
    return {"entries": entries, "bullets": {b["id"]: b for b in bullets}}


def _op_add_entry(body: dict, op: dict, index: dict) -> None:
    entry = index["entries"][op["entry_id"]]
    layout = bank.layout_for(entry.get("kind"))
    key = (op.get("section") or "").strip() or layout.default_section
    section = _section_for(body, key, layout)
    _insert(section.setdefault("placements", []), _snapshot(entry), op.get("position"))


def _op_drop_entry(body: dict, op: dict, _index: dict) -> None:
    section, placement = _locate_placement(body, op.get("placement_id"))
    section["placements"].remove(placement)


def _op_move_entry(body: dict, op: dict, _index: dict) -> None:
    section, placement = _locate_placement(body, op.get("placement_id"))
    section["placements"].remove(placement)
    _insert(section["placements"], placement, op.get("position"))


def _op_rename_section(body: dict, op: dict, _index: dict) -> None:
    label = (op.get("label") or "").strip()
    if not label:
        raise ValueError("A section needs a label.")
    _locate_section(body, op.get("section_id"))["label"] = label


def _op_add_bullet(body: dict, op: dict, index: dict) -> None:
    _, placement = _locate_placement(body, op.get("placement_id"))
    source = index["bullets"][op["bullet_id"]]
    # Naming an id the bank holds is not enough on its own. Hanging one
    # record's achievement under another claims the second did the first's
    # work, which is the thing the closed algebra exists to prevent, and the
    # snapshot anchors to the foreign bullet, so editing that bullet in the
    # bank writes the misattribution back into the draft.
    if source["entry_id"] != placement.get("entry_id"):
        raise ValueError(
            f"Bullet {source['id']} belongs to entry {source['entry_id']}, "
            f"not to the record placed at {op.get('placement_id')!r}."
        )
    _insert(placement.setdefault("bullets", []), _snapshot_bullet(source), op.get("position"))


def _op_drop_bullet(body: dict, op: dict, _index: dict) -> None:
    _, placement = _locate_placement(body, op.get("placement_id"))
    placement["bullets"].remove(_locate_bullet(placement, op.get("bullet_ref")))


def _op_move_bullet(body: dict, op: dict, _index: dict) -> None:
    _, placement = _locate_placement(body, op.get("placement_id"))
    bullet = _locate_bullet(placement, op.get("bullet_ref"))
    placement["bullets"].remove(bullet)
    _insert(placement["bullets"], bullet, op.get("position"))


def _op_rewrite_bullet(body: dict, op: dict, index: dict) -> None:
    _, placement = _locate_placement(body, op.get("placement_id"))
    bullet = _locate_bullet(placement, op.get("bullet_ref"))
    text = (op.get("text") or "").strip()
    if not text:
        raise ValueError("A rewritten bullet needs some text.")
    bullet["text"] = text
    source = index["bullets"].get(bullet.get("source_bullet_id"))
    # Only a rewrite that lands on the bank's own current wording answers the
    # drift, which is what accepting a sync offer does. A tailoring pass
    # writes something else and has never shown the user what the bank now
    # says, so re-anchoring there would withdraw a decision they were owed.
    if source is not None and source["text"].strip() == text:
        bullet["source_text"] = text


OPERATIONS: dict[str, Callable[[dict, dict, dict], None]] = {
    "AddEntry": _op_add_entry,
    "DropEntry": _op_drop_entry,
    "MoveEntry": _op_move_entry,
    "RenameSection": _op_rename_section,
    "AddBullet": _op_add_bullet,
    "DropBullet": _op_drop_bullet,
    "MoveBullet": _op_move_bullet,
    "RewriteBullet": _op_rewrite_bullet,
}

# Operations that cannot do their job without the id they name.
REQUIRED_BANK_REF = {"AddEntry": "entry_id", "AddBullet": "bullet_id"}


def _check_bank_refs(ops: list[dict], index: dict) -> None:
    """Refuse any operation naming a record the bank does not hold.

    This is the structural half of "never invent experience the student does
    not have". A tailoring pass can reorder, drop and reword what is already
    there, and an operation that reaches for anything else fails here rather
    than being talked out of it by a prompt.
    """
    for op in ops:
        name = op.get("op")
        if name not in OPERATIONS:
            raise ValueError(f"'{name}' is not an operation a proposal may use.")
        for field, pool in (("entry_id", "entries"), ("bullet_id", "bullets")):
            value = op.get(field)
            if value is None:
                if REQUIRED_BANK_REF.get(name) == field:
                    raise ValueError(f"A {name} operation has to name a {field}.")
                continue
            if value not in index[pool]:
                raise ValueError(
                    f"A {name} operation names {field} {value}, which is not in the bank."
                )


# ------------------------------------------------------------------ proposals

def get_proposal(proposal_id: int) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM draft_proposals WHERE id = ?", (proposal_id,)).fetchone()
    if row is None:
        raise DraftNotFound(f"Proposal {proposal_id} not found")
    return proposal_dict(row)


def list_proposals(draft_id: int) -> list[dict[str, Any]]:
    get_draft(draft_id)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM draft_proposals WHERE draft_id = ? ORDER BY id DESC", (draft_id,)
        ).fetchall()
    listed = []
    for row in rows:
        try:
            listed.append(proposal_dict(row))
        except CorruptDraft as exc:
            logger.warning("Proposal %s has unreadable operations: %s", row["id"], exc)
            listed.append({**dict(row), "operations": []})
    return listed


_NOT_IDENTITY = ("accepted", "rationale")


def _identity(op: dict) -> tuple:
    """What has to match for a submitted operation to be one that was offered.

    The accept state is the user's answer and the rationale is the author's
    reasoning, so neither is part of which operation this is. A missing field
    and a field set to None mean the same thing throughout the algebra, so an
    absent value is left out rather than compared.
    """
    return tuple(sorted(
        (field, value) for field, value in op.items()
        if field not in _NOT_IDENTITY and value is not None
    ))


def _reviewed(stored: list[dict], submitted: Optional[list[dict]]) -> list[dict]:
    """The operations that were offered, carrying the user's decision on each.

    The proposal row is the record of what was offered. Storing the client's
    list in its place let a resolve introduce operations nobody proposed and
    rewrite the evidence of the offer in the same write, which makes the audit
    trail a record of what was applied rather than of what was proposed.

    What comes back is the offered list in the offered order, with the accept
    states filled in. Paired by position rather than by content, because two
    identical operations are indistinguishable by content: matching on it
    would hand them both whichever answer arrived last.
    """
    if submitted is None:
        return [dict(op, accepted=op.get("accepted", True)) for op in stored]
    if len(submitted) != len(stored):
        raise ValueError(
            f"This proposal offered {len(stored)} operations and {len(submitted)} came back."
        )
    for offered, answer in zip(stored, submitted):
        if _identity(offered) != _identity(answer):
            raise ValueError(f"A {answer.get('op')} operation was not part of this proposal.")
    return [dict(op, accepted=bool(answer.get("accepted", True)))
            for op, answer in zip(stored, submitted)]


def apply_proposal(proposal_id: int, operations: Optional[list[dict]] = None) -> dict[str, Any]:
    """Apply the accepted operations of a proposal to its draft.

    Idempotent: a proposal that is no longer pending has already had its say,
    so a repeat call returns the draft untouched rather than applying the same
    run of operations on top of itself.
    """
    proposal = get_proposal(proposal_id)
    draft = get_draft(proposal["draft_id"])
    if proposal["status"] != "pending":
        return draft

    reviewed = _reviewed(proposal["operations"], operations)
    accepted = [op for op in reviewed if op["accepted"]]

    with get_db() as conn:
        index = _bank_index(conn)
    _check_bank_refs(accepted, index)

    def run(body: dict) -> None:
        for op in accepted:
            OPERATIONS[op["op"]](body, op, index)

    with get_db() as conn:
        # Compare-and-set rather than a plain UPDATE: two calls racing on the
        # same proposal must apply it once, not twice.
        claimed = conn.execute(
            """UPDATE draft_proposals SET status = 'applied', resolved_at = ?, operations = ?
               WHERE id = ? AND status = 'pending'""",
            (_now(), json.dumps(reviewed), proposal_id),
        ).rowcount
        if claimed:
            _mutate_body(conn, draft["id"], run)
    return get_draft(draft["id"])


def dismiss_proposal(proposal_id: int) -> dict[str, Any]:
    """Drop a proposal without reading what it offered.

    Deliberately not through `get_proposal`: dismissing needs nothing out of
    the operations column, and a proposal whose column will not parse is the
    one the user most needs to be able to get rid of.
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT draft_id FROM draft_proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if row is None:
            raise DraftNotFound(f"Proposal {proposal_id} not found")
        conn.execute(
            """UPDATE draft_proposals SET status = 'dismissed', resolved_at = ?
               WHERE id = ? AND status = 'pending'""",
            (_now(), proposal_id),
        )
    return get_draft(row["draft_id"])


def sync_proposal(draft_id: int) -> Optional[dict[str, Any]]:
    """Offer to reconcile bullets the bank has reworded since they were placed.

    Drift is measured against `source_text`, the wording the bank had when the
    bullet was snapshotted, not against the draft's own text: a line the user
    deliberately tailored has moved away from the bank on purpose and is not
    out of date.

    Convergent. Running it again on an unchanged draft hands back the standing
    offer unchanged, replaces it once the drift behind it moves, and withdraws
    it entirely when nothing differs. The list endpoint runs this on every
    read, so an offer re-minted each time would 404 the id the client is
    holding the moment the list refreshed under it.
    """
    draft = get_draft(draft_id)
    with get_db() as conn:
        current = {row["id"]: row["text"] for row in conn.execute("SELECT id, text FROM bank_bullets")}

    ops = []
    for _section, placement in _placements(draft["body"]):
        for bullet in placement.get("bullets") or []:
            source_id = bullet.get("source_bullet_id")
            if source_id not in current or bullet.get("source_text") == current[source_id]:
                continue
            ops.append({
                "op": "RewriteBullet",
                "accepted": True,
                "rationale": f"The bank now reads: {current[source_id]}",
                "bullet_id": source_id,
                "placement_id": placement.get("ref"),
                "bullet_ref": bullet.get("ref"),
                "text": current[source_id],
            })

    with get_db() as conn:
        standing = conn.execute(
            """SELECT * FROM draft_proposals
               WHERE draft_id = ? AND kind = 'sync' AND status = 'pending'
               ORDER BY id DESC""",
            (draft_id,),
        ).fetchone()
        if standing is not None and proposal_dict(standing)["operations"] == ops:
            return proposal_dict(standing)
        conn.execute(
            "DELETE FROM draft_proposals WHERE draft_id = ? AND kind = 'sync' AND status = 'pending'",
            (draft_id,),
        )
        if not ops:
            return None
        noun = "bullet" if len(ops) == 1 else "bullets"
        cursor = conn.execute(
            """INSERT INTO draft_proposals (draft_id, kind, status, summary, operations, created_at)
               VALUES (?, 'sync', 'pending', ?, ?, ?)""",
            (draft_id, f"{len(ops)} {noun} changed in the bank since this draft was composed.",
             json.dumps(ops), _now()),
        )
        proposal_id = int(cursor.lastrowid)
    return get_proposal(proposal_id)


# ------------------------------------------------------------------- coverage

def draft_segments(body: dict) -> list[tuple[str, str]]:
    """One (placement ref, plain text) pair per entry on the page.

    The URL is left out deliberately. A repo address like
    `github.com/me/pytorch-oracle` would otherwise mark PyTorch covered by a
    keyword the resume never actually claims.
    """
    segments = []
    for _section, placement in _placements(body):
        parts = [placement.get("title"), placement.get("organization"), placement.get("detail")]
        parts += [bullet.get("text") for bullet in placement.get("bullets") or []]
        segments.append((placement.get("ref") or "", " ".join(part for part in parts if part)))
    return segments


def coverage_report(draft_id: int) -> dict[str, Any]:
    """How much of the job post's vocabulary the draft actually says.

    The one place the composition half and the keyword half meet.
    """
    draft = get_draft(draft_id)
    post_id = draft.get("job_post_id")
    terms: list[dict] = []
    if post_id is not None:
        try:
            terms = jobposts.get_post(post_id)["keywords"]
        except jobposts.JobPostNotFound:
            terms = []

    if not terms:
        return {"draft_id": draft_id, "job_post_id": post_id, "covered": 0, "total": 0, "keywords": []}

    results = keywords.coverage(terms, draft_segments(draft["body"]))
    return {
        "draft_id": draft_id,
        "job_post_id": post_id,
        "covered": sum(1 for result in results if result.get("covered")),
        "total": len(results),
        "keywords": results,
    }


# ----------------------------------------------------------------------- push

def _rendered(draft: dict) -> str:
    return resume_render.render_document(get_setting("resume_template") or "", draft["body"])


def _instance_latex(instance_id: Optional[int]) -> Optional[str]:
    if instance_id is None:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT latex FROM resume_instances WHERE id = ?", (instance_id,)
        ).fetchone()
    return None if row is None else (row["latex"] or "")


def _result(draft: dict, latex: str, *, pushed: bool, diverged: bool) -> dict[str, Any]:
    return {
        "draft_id": draft["id"],
        "resume_instance_id": draft.get("resume_instance_id"),
        "latex": latex,
        "pushed": pushed,
        "diverged": diverged,
        "pushed_latex": draft.get("pushed_latex"),
        "pushed_at": draft.get("pushed_at"),
    }


def _would_overwrite(draft: dict, current: Optional[str], latex: str) -> bool:
    """Whether writing `latex` would discard work nobody can get back.

    Not simply "the variant changed". There is nothing to lose when there is
    no variant behind the draft, and nothing to lose when the variant already
    holds exactly what the push would write.
    """
    if current is None:
        return False
    return current != (draft.get("pushed_latex") or "") and current != latex


def render_draft(draft_id: int) -> dict[str, Any]:
    """What a push would write, and whether it would overwrite a hand-edit."""
    draft = get_draft(draft_id)
    latex = _rendered(draft)
    current = _instance_latex(draft.get("resume_instance_id"))
    return _result(draft, latex, pushed=False,
                   diverged=_would_overwrite(draft, current, latex))


def push_draft(draft_id: int, *, force: bool = False) -> dict[str, Any]:
    """Write the rendered draft into its resume variant.

    `pushed_latex` holds exactly what the last push wrote, so a variant whose
    source no longer matches it has been edited somewhere else and overwriting
    it would throw that work away. Refusing is the same call `latex_compat`
    makes when it declines to rewrite a document on its way to the engine.
    """
    draft = get_draft(draft_id)
    latex = _rendered(draft)

    instance_id = draft.get("resume_instance_id")
    current = _instance_latex(instance_id)
    if current is None:
        # `pushed_latex` describes a row nobody can lose work from, so there
        # is nothing here to refuse over, and minting the variant on this
        # branch alone is what stops a refused push leaving one behind.
        #
        # `resumes.create_instance` opens connections of its own, so it has to
        # finish before this function opens a write of its own.
        instance_id = resumes.create_instance(draft["name"], latex_source="")["id"]
    elif _would_overwrite(draft, current, latex) and not force:
        raise PushConflict(draft_id, instance_id, latex, current,
                           draft.get("pushed_latex") or "")

    resumes.update_instance(instance_id, {"latex": latex})
    with get_db() as conn:
        conn.execute(
            """UPDATE resume_drafts
               SET resume_instance_id = ?, pushed_latex = ?, pushed_at = ?, updated_at = ?
               WHERE id = ?""",
            (instance_id, latex, _now(), _now(), draft_id),
        )
    return _result(get_draft(draft_id), latex, pushed=True, diverged=False)
