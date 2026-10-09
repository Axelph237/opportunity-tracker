"""Tailoring a resume by rearranging the slots in its own source.

The same guarantee as the draft tailoring this replaces, carried over to the
document. Claude may only reorder, drop and reword what the bank already
holds. There is no operation that writes a new record, so a proposal cannot
put experience into a resume that the user did not enter.

Two things are different now that the document is the truth.

A block has no id. It is a stretch of someone's LaTeX, so an operation names
it by where it sits. That makes a proposal only valid against the document it
was built from, which is why every proposal carries a fingerprint of the
slots it saw and refuses to apply against anything else.

A block has no provenance either. Nothing in the source records which bank
record it came from, so the entry behind a block is recovered by rendering
each bank record and looking for an exact match. A block that was hand-edited
matches nothing, and the operations that need to know its record are refused
for it rather than guessed at.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Literal, Optional

import bank
import compose
import jobposts
import keywords
import resume_render
import resumes
import slots
import tailor
from claude_cli import ClaudeCallError, run_claude
from database import get_db
from tailor import MAX_BULLET_CHARS, TailorError, extract_json

logger = logging.getLogger(__name__)

TIMEOUT = 180

SYSTEM_PROMPT = """You are tailoring a resume to one job advertisement.

The resume is a LaTeX document with named slots. A slot is a region you may
rearrange. You address a block by its index within its slot, and a bullet by
its index within its block, exactly as they are numbered below.

Return JSON only: {"summary": "...", "operations": [...]}

Every operation is one of these and nothing else:
  {"op":"AddEntry","slot":"...","entry_id":N,"position":N,"rationale":"..."}
  {"op":"DropEntry","slot":"...","block":N,"rationale":"..."}
  {"op":"MoveEntry","slot":"...","block":N,"position":N,"rationale":"..."}
  {"op":"AddBullet","slot":"...","block":N,"bullet_id":N,"rationale":"..."}
  {"op":"DropBullet","slot":"...","block":N,"bullet":N,"rationale":"..."}
  {"op":"MoveBullet","slot":"...","block":N,"bullet":N,"position":N,"rationale":"..."}
  {"op":"RewriteBullet","slot":"...","block":N,"bullet":N,"text":"...","rationale":"..."}

Rules that matter more than the tailoring:
- Never state anything the bank does not already support. A rewrite may
  sharpen wording, lead with a stronger verb, or mirror the ad's language.
  It may not add a number, a tool, a scope or an outcome that is not there.
- Put what the ad asks for first, in the order the ad asks for it.
- A bullet starts with a strong action verb, is one or two lines, and never
  three. Present tense for current work, past for finished work.
- Never use assisted, observed, helped or participated.
- Every operation carries a rationale naming what in the ad it serves.
"""


# ------------------------------------------------------------- the algebra

BankField = Literal["entry_id", "bullet_id"]


@dataclass(frozen=True)
class OpShape:
    """What one operation has to name before it is worth storing."""

    bank_field: Optional[BankField] = None
    block: bool = False
    bullet: bool = False
    # The bullet must belong to the bank record this block was rendered from,
    # which is the rule that stops one employer's work moving under another.
    same_entry: bool = False
    text: bool = False


OP_SHAPES: dict[str, OpShape] = {
    "AddEntry": OpShape(bank_field="entry_id"),
    "DropEntry": OpShape(block=True),
    "MoveEntry": OpShape(block=True),
    "AddBullet": OpShape(bank_field="bullet_id", block=True, same_entry=True),
    "DropBullet": OpShape(block=True, bullet=True),
    "MoveBullet": OpShape(block=True, bullet=True),
    "RewriteBullet": OpShape(block=True, bullet=True, text=True),
}


@dataclass(frozen=True)
class Anchors:
    """Everything an operation is allowed to name, for one document."""

    bank: dict[BankField, frozenset[int]]
    entry_of_bullet: dict[int, int]
    # slot key -> how many blocks it holds
    blocks: dict[str, int]
    # (slot key, block index) -> how many bullets that block holds
    bullets: dict[tuple[str, int], int]
    # (slot key, block index) -> the bank record it was rendered from, if any
    entry_of_block: dict[tuple[str, int], Optional[int]]


def _entry_by_heading(entries: list[dict[str, Any]]) -> dict[str, int]:
    """Each bank record keyed by the heading line it renders to.

    Recovering provenance the document does not store. Exact, because the
    block was written by this same renderer; a block somebody edited by hand
    simply will not be in here.
    """
    index: dict[str, int] = {}
    for entry in entries:
        rendered = resume_render.render_placement(bank.printable(entry))
        heading = rendered.split("\n", 1)[0].strip()
        if heading:
            index.setdefault(heading, entry["id"])
    return index


def _anchors(entries: list[dict[str, Any]], document: list[dict[str, Any]]) -> Anchors:
    by_heading = _entry_by_heading(entries)
    blocks: dict[str, int] = {}
    bullets: dict[tuple[str, int], int] = {}
    entry_of_block: dict[tuple[str, int], Optional[int]] = {}

    for slot in document:
        key = slot["key"]
        rows = slot.get("blocks") or []
        blocks[key] = len(rows)
        for index, block in enumerate(rows):
            bullets[(key, index)] = len(block.get("bullets") or [])
            heading = (block.get("raw") or "").split("\n", 1)[0].strip()
            entry_of_block[(key, index)] = by_heading.get(heading)

    return Anchors(
        bank={
            "entry_id": frozenset(entry["id"] for entry in entries),
            "bullet_id": frozenset(
                bullet["id"] for entry in entries for bullet in entry.get("bullets") or []
            ),
        },
        entry_of_bullet={
            bullet["id"]: entry["id"]
            for entry in entries
            for bullet in entry.get("bullets") or []
        },
        blocks=blocks,
        bullets=bullets,
        entry_of_block=entry_of_block,
    )


def _rejection(op: dict[str, Any], anchors: Anchors) -> Optional[str]:
    """Why this operation may not be stored, or None if it may.

    Table-driven off `OP_SHAPES`, so a ninth operation is a row there and a
    row in the test's expected algebra rather than another branch here.
    """
    name = op["op"]
    shape = OP_SHAPES.get(name)
    if shape is None:
        return f"{name or 'an unnamed operation'} is not an operation a proposal may use"

    key = op["slot"]
    if key not in anchors.blocks:
        return f"{name} names slot {key!r}, which this resume does not have"

    if shape.bank_field:
        value = op[shape.bank_field]
        if value not in anchors.bank[shape.bank_field]:
            return f"{name} names {shape.bank_field} {value!r}, which is not in the bank"

    if shape.block:
        index = op["block"]
        if index is None or not 0 <= index < anchors.blocks[key]:
            return f"{name} names block {index!r}, which is not in slot {key!r}"

    if shape.bullet:
        count = anchors.bullets.get((key, op["block"]), 0)
        at = op["bullet"]
        if at is None or not 0 <= at < count:
            return f"{name} names bullet {at!r}, which is not in that block"

    if shape.same_entry:
        owner = anchors.entry_of_block.get((key, op["block"]))
        if owner is None:
            return (
                f"{name} targets a block this resume cannot trace back to a bank record, "
                "so there is no way to tell whose bullet belongs under it"
            )
        if anchors.entry_of_bullet.get(op["bullet_id"]) != owner:
            return f"{name} would put a bullet under a record it is not part of"

    if shape.text:
        if not op["text"]:
            return f"{name} has no replacement text"
        if len(op["text"]) > MAX_BULLET_CHARS:
            return f"{name} is longer than the {MAX_BULLET_CHARS} characters a bullet can be"

    return None


def _normalize_op(entry: Any) -> dict[str, Any]:
    data = entry if isinstance(entry, dict) else {}
    return {
        "op": str(data.get("op") or "").strip(),
        "slot": str(data.get("slot") or "").strip().lower(),
        "block": tailor._int(data.get("block")),
        "bullet": tailor._int(data.get("bullet")),
        "position": tailor._int(data.get("position")),
        "entry_id": tailor._int(data.get("entry_id")),
        "bullet_id": tailor._int(data.get("bullet_id")),
        "text": tailor._text(data.get("text"), MAX_BULLET_CHARS),
        "rationale": tailor._text(data.get("rationale"), 400),
        "accepted": True,
    }


def _fingerprint(document: list[dict[str, Any]]) -> str:
    """What the offer was built against, so it cannot be applied to something else."""
    shape = [
        [slot["key"], [block.get("raw", "") for block in slot.get("blocks") or []]]
        for slot in document
    ]
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode()).hexdigest()


# ------------------------------------------------------------- the proposal

def _document(instance_id: int) -> list[dict[str, Any]]:
    return compose.read(instance_id)


def _slot_block(document: list[dict[str, Any]]) -> str:
    """The resume as the model addresses it: slots, blocks, bullets, numbered."""
    lines: list[str] = []
    for slot in document:
        lines.append(f'slot "{slot["key"]}"')
        for index, block in enumerate(slot.get("blocks") or []):
            if block.get("kind") != "entry":
                lines.append(f"  [{index}] (your own LaTeX, leave it alone)")
                continue
            shown = block.get("args_text") or block.get("args") or []
            lines.append(f"  [{index}] {' | '.join(part for part in shown if part)}")
            for at, text in enumerate(block.get("bullets_text") or block.get("bullets") or []):
                lines.append(f"      ({at}) {text}")
    return "\n".join(lines) or "(this resume has no slots)"


def _coverage(instance_id: int, post: dict[str, Any], document: list[dict[str, Any]]) -> list[dict]:
    segments = [
        (f"{slot['key']}:{index}", " ".join(
            [*(block.get("args_text") or []), *(block.get("bullets_text") or [])]
        ))
        for slot in document
        for index, block in enumerate(slot.get("blocks") or [])
    ]
    return keywords.coverage(post.get("keywords") or [], segments)


def coverage_report(instance_id: int) -> dict[str, Any]:
    """The ad's vocabulary against what this document actually says.

    Measured on the slot contents rather than the whole source, because the
    preamble and the macro names are not things the resume claims.
    """
    instance = resumes.get_instance(instance_id)
    post_id = instance.get("job_post_id")
    blank = {
        "resume_instance_id": instance_id,
        "job_post_id": post_id,
        "covered": 0,
        "total": 0,
        "keywords": [],
    }
    if post_id is None:
        return blank
    try:
        post = jobposts.get_post(post_id)
    except jobposts.JobPostNotFound:
        return blank

    results = _coverage(instance_id, post, _document(instance_id))
    return {
        **blank,
        "covered": sum(1 for row in results if row.get("covered")),
        "total": len(results),
        "keywords": results,
    }


def propose(instance_id: int, *, model: Optional[str] = None) -> dict[str, Any]:
    """Ask for a set of changes, keep only the ones the algebra allows."""
    instance = resumes.get_instance(instance_id)
    document = _document(instance_id)
    if not document:
        raise TailorError(
            "This resume has no slots yet, so there is nothing a tailoring pass could move. "
            "Mark a region of its source first."
        )

    post_id = instance.get("job_post_id")
    if post_id is None:
        raise TailorError("Attach the job ad to this resume first; there is nothing to tailor to.")
    post = jobposts.get_post(post_id)

    entries = bank.list_entries()
    prompt = "\n\n".join(
        [
            tailor._post_block(post),
            tailor._keyword_block(post),
            tailor._bank_block(entries),
            "Resume as it stands:\n" + _slot_block(document),
            tailor._coverage_block(
                {"keywords": _coverage(instance_id, post, document)}
            ),
        ]
    )

    try:
        data = extract_json(
            run_claude(prompt, system=SYSTEM_PROMPT, model=model, timeout=TIMEOUT)
        )
    except (ClaudeCallError, ValueError) as exc:
        raise TailorError(f"Could not read a tailoring plan: {exc}") from exc

    anchors = _anchors(entries, document)
    kept: list[dict[str, Any]] = []
    rejected: list[str] = []
    for raw in data.get("operations") or []:
        op = _normalize_op(raw)
        why = _rejection(op, anchors)
        if why:
            rejected.append(why)
            continue
        kept.append(op)

    if rejected:
        logger.info("Dropped %d tailoring operations: %s", len(rejected), "; ".join(rejected[:5]))
    if not kept:
        raise TailorError(tailor._nothing_usable(rejected))

    summary = tailor._summary(data, kept=len(kept), dropped=len(rejected))
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO resume_proposals
                   (resume_instance_id, status, summary, operations, fingerprint, created_at)
               VALUES (?, 'pending', ?, ?, ?, ?)""",
            (instance_id, summary, json.dumps(kept), _fingerprint(document), tailor._now()),
        )
        proposal_id = cursor.lastrowid
    return get_proposal(proposal_id)


def proposal_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    try:
        data["operations"] = json.loads(data.get("operations") or "[]")
    except (TypeError, ValueError):
        data["operations"] = []
    return data


def get_proposal(proposal_id: int) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM resume_proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
    if row is None:
        raise TailorError(f"Proposal {proposal_id} not found")
    return proposal_dict(row)


def list_proposals(instance_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM resume_proposals WHERE resume_instance_id = ?
               ORDER BY id DESC""",
            (instance_id,),
        ).fetchall()
    return [proposal_dict(row) for row in rows]


# -------------------------------------------------------------- applying it

def _tagged(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each block carrying the position it had when the offer was made.

    Operations address the snapshot, not the list as it is being rebuilt, so
    the second operation of a set must not land somewhere different because
    the first one shifted everything after it.
    """
    return [{"at": index, "block": dict(block)} for index, block in enumerate(blocks)]


def _find(rows: list[dict[str, Any]], at: int) -> Optional[int]:
    for position, row in enumerate(rows):
        if row["at"] == at:
            return position
        
    return None


def _move(rows: list[Any], frm: int, to: int) -> None:
    rows.insert(max(0, min(to, len(rows) - 1)), rows.pop(frm))


def _apply_one(op: dict[str, Any], state: dict[str, list[dict[str, Any]]],
               entries: dict[int, dict[str, Any]]) -> None:
    rows = state[op["slot"]]
    name = op["op"]

    if name == "AddEntry":
        entry = entries[op["entry_id"]]
        placed = slots.parse(resume_render.render_placement(bank.printable(entry)))
        new = [{"at": None, "block": block.as_dict()} for block in placed]
        at = len(rows) if op["position"] is None else max(0, min(op["position"], len(rows)))
        rows[at:at] = new
        return

    found = _find(rows, op["block"])
    if found is None:
        # Already dropped by an earlier accepted operation. Nothing to do,
        # rather than an error: the user accepted both and meant both.
        return
    block = rows[found]["block"]

    if name == "DropEntry":
        rows.pop(found)
    elif name == "MoveEntry":
        _move(rows, found, op["position"] if op["position"] is not None else found)
    elif name == "AddBullet":
        source = next(
            (b for e in entries.values() for b in e.get("bullets") or []
             if b["id"] == op["bullet_id"]),
            None,
        )
        if source:
            block.setdefault("bullets", []).append(resume_render.escape(source["text"]))
    elif name in {"DropBullet", "MoveBullet", "RewriteBullet"}:
        bullets = block.get("bullets") or []
        at = op["bullet"]
        if not 0 <= at < len(bullets):
            return
        if name == "DropBullet":
            bullets.pop(at)
        elif name == "MoveBullet":
            _move(bullets, at, op["position"] if op["position"] is not None else at)
        else:
            bullets[at] = resume_render.escape(op["text"])
        block["bullets"] = bullets


def apply_proposal(proposal_id: int, operations: Optional[list[dict]] = None) -> dict[str, Any]:
    """Apply the accepted operations, against the document they were offered on.

    The offer is the record of what was proposed, so a decision fills in the
    accept states rather than replacing the list. Anything the user left
    unticked is simply not run.
    """
    proposal = get_proposal(proposal_id)
    if proposal["status"] != "pending":
        raise TailorError("This proposal has already been resolved.")

    instance_id = proposal["resume_instance_id"]
    document = _document(instance_id)
    if _fingerprint(document) != (proposal["fingerprint"] or ""):
        raise TailorError(
            "This resume has changed since these changes were worked out, and they name "
            "positions that have moved. Ask for a fresh set."
        )

    stored = tailor_reviewed(proposal["operations"], operations)
    entries = {entry["id"]: entry for entry in bank.list_entries()}
    state = {slot["key"]: _tagged(slot.get("blocks") or []) for slot in document}

    for op in stored:
        if op.get("accepted"):
            _apply_one(op, state, entries)

    for key, rows in state.items():
        blocks = [
            slots.Block(
                kind=row["block"].get("kind") or "opaque",
                raw=row["block"].get("raw") or "",
                heading=row["block"].get("heading"),
                args=list(row["block"].get("args") or []),
                bullets=list(row["block"].get("bullets") or []),
                in_list=bool(row["block"].get("in_list", True)),
            )
            for row in rows
        ]
        compose.set_blocks(instance_id, key, [block.as_dict() for block in blocks])

    with get_db() as conn:
        conn.execute(
            """UPDATE resume_proposals SET status = 'applied', operations = ?, resolved_at = ?
               WHERE id = ? AND status = 'pending'""",
            (json.dumps(stored), tailor._now(), proposal_id),
        )
    return get_proposal(proposal_id)


def dismiss_proposal(proposal_id: int) -> dict[str, Any]:
    get_proposal(proposal_id)
    with get_db() as conn:
        conn.execute(
            """UPDATE resume_proposals SET status = 'dismissed', resolved_at = ?
               WHERE id = ? AND status = 'pending'""",
            (tailor._now(), proposal_id),
        )
    return get_proposal(proposal_id)


def tailor_reviewed(stored: list[dict], submitted: Optional[list[dict]]) -> list[dict]:
    """The offered list in the offered order, with the accept states filled in.

    Paired by position rather than by content, because two identical
    operations cannot be told apart by content and matching on it would hand
    them both whichever answer arrived last.
    """
    if submitted is None:
        return [dict(op, accepted=op.get("accepted", True)) for op in stored]
    if len(submitted) != len(stored):
        raise TailorError(
            f"This proposal offered {len(stored)} operations and {len(submitted)} came back."
        )
    return [
        dict(op, accepted=bool(answer.get("accepted", True)))
        for op, answer in zip(stored, submitted)
    ]
