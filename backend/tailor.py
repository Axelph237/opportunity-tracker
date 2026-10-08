"""Agent tailoring: rearranging one draft to answer one advertisement."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import bank
import drafts
import jobposts
from claude_cli import ClaudeCallError, extract_json, run_claude
from database import get_db

logger = logging.getLogger(__name__)

MAX_POST_CHARS = 8000
MAX_BANK_CHARS = 12_000
MAX_OPS = 40

MAX_BULLET_CHARS = 300
MAX_RAW_TEXT_CHARS = MAX_BULLET_CHARS * 10

MAX_REF_CHARS = 80
MAX_LABEL_CHARS = 120
MAX_RATIONALE_CHARS = 400
MAX_SUMMARY_CHARS = 2000

MAX_IMPORT_CHARS = 12_000
MAX_IMPORT_ENTRIES = 40
MAX_IMPORT_BULLETS = 12

TAILOR_TIMEOUT = 300
IMPORT_TIMEOUT = 300

BUCKET_LABELS = {
    "technical": "Technical terms",
    "verb": "Action verbs",
    "professional": "Professional skills",
}


class TailorError(RuntimeError):
    """Raised when a tailoring pass or an import cannot produce anything usable."""


TAILOR_SYSTEM_PROMPT = """You are a careers adviser rearranging one resume draft to answer one job
advertisement, for a Computer Science / Quantum Engineering student.

You may only rearrange and reword what the student has already written. Every operation you return
names a record that already exists: an entry or bullet id from the bank inventory, or a section,
placement or bullet ref from the current draft. There is no operation that introduces a record, and
you must not invent a fact. A rewrite has to be supported by the bullet it is anchored to, rephrased
or re-emphasised, never extended with an achievement, a tool or a number that bullet does not
already contain. Operations naming anything else are discarded before the student sees them, so
reaching for experience they do not have costs you a suggestion and gains nothing.

Return ONLY a valid JSON object with exactly these fields:
{
  "summary": "one paragraph on what you changed and why the draft now answers this advertisement",
  "operations": [
    {
      "op": "AddEntry|DropEntry|MoveEntry|RenameSection|AddBullet|DropBullet|MoveBullet|RewriteBullet",
      "rationale": "one sentence, the single reason the student would accept this one change",
      "entry_id": integer bank entry id, for AddEntry,
      "bullet_id": integer bank bullet id, for AddBullet,
      "section": "the section label an AddEntry lands under, or null for that kind's default",
      "section_id": "the draft section ref a RenameSection retitles",
      "label": "the new section label, for RenameSection",
      "placement_id": "the draft placement ref the operation acts on",
      "bullet_ref": "the bullet ref inside that placement, for DropBullet, MoveBullet and RewriteBullet",
      "position": integer 0-based index to insert at, or null for the end,
      "text": "the rewritten bullet, for RewriteBullet"
    }
  ]
}
Give the fields an operation uses and null for the rest.

A resume gets about thirty seconds against the words in the advertisement, so write to what it asks
for, in the order it asks for it:
- Order sections, entries and bullets so the first thing read is the thing the advertisement leads
  with, and the most relevant bullets sit at the top of their entry.
- Reuse the advertisement's own verbs and terms wherever the underlying experience genuinely
  supports them. Mirroring its wording beats finding a better synonym for it.
- Start every rewritten bullet with a strong action verb. Never open one with assisted, observed,
  helped or participated.
- Implied first person: no I, we, my, our or their. No trailing period. One or two lines, never three.
- Present tense for work still going on, past tense for work that has finished.
- More bullets on recent experience, fewer on older.
- Quantify wherever the source bullet already gives you a number, a scale or a duration to quantify
  with. Never supply one it does not contain.

Order the operations most impactful first and return at most 40. Do not include any text outside the
JSON object."""


IMPORT_SYSTEM_PROMPT = """You are reading a student's existing resume and breaking it back into the
reusable records a resume builder composes from.

Transcribe, do not improve. Every record and every bullet has to come from the text in front of you,
worded the way it words them. Do not merge two roles into one, do not split one bullet into two, and
do not add an accomplishment, a tool or a date the resume does not state. Leave a field null rather
than guessing at it. Leave out anything that is not part of a record: a name, an address, a phone
number, an email or a link bar belongs to the document heading, not to these records.

Return ONLY a valid JSON object with exactly these fields:
{
  "entries": [
    {
      "kind": "education|experience|project|skill_group|award|publication|presentation|certification",
      "title": "the role, degree, project or skill-group name",
      "organization": "the employer, school or venue, or null",
      "location": "where it happened, or null",
      "start_date": "worded as the resume words it, e.g. 'Jun 2026', or null",
      "end_date": "worded as the resume words it, or null when the record is still running",
      "is_current": true when the record is still running,
      "url": "a link the resume gives for this record, or null",
      "detail": "a one-line subtitle the resume gives this record, or null",
      "bullets": ["each bullet under this record, transcribed as written"]
    }
  ]
}
A skill_group's title is the category, such as "Languages" or "Frameworks", and its bullets are the
individual terms, one term per bullet. Return the records in the order the resume lists them.
Do not include any text outside the JSON object."""


BankField = Literal["entry_id", "bullet_id"]


@dataclass(frozen=True)
class OpShape:
    """What one operation has to name before it is worth storing."""

    bank_field: Optional[BankField] = None
    placement: bool = False
    bullet_ref: bool = False
    section_id: bool = False
    label: bool = False
    text: bool = False


# This gate runs when the proposal is built; `drafts._check_bank_refs` runs
# again when the user accepts it, because the bank can change in between.
OP_SHAPES: dict[str, OpShape] = {
    "AddEntry": OpShape(bank_field="entry_id"),
    "DropEntry": OpShape(placement=True),
    "MoveEntry": OpShape(placement=True),
    "RenameSection": OpShape(section_id=True, label=True),
    "AddBullet": OpShape(bank_field="bullet_id", placement=True),
    "DropBullet": OpShape(placement=True, bullet_ref=True),
    "MoveBullet": OpShape(placement=True, bullet_ref=True),
    "RewriteBullet": OpShape(placement=True, bullet_ref=True, text=True),
}


@dataclass(frozen=True)
class Anchors:
    """Every id and ref an operation is allowed to name, for one draft."""

    bank: dict[BankField, frozenset[int]]
    sections: frozenset[str]
    bullet_refs_by_placement: dict[str, frozenset[str]]


def _anchors(entries: list[dict[str, Any]], body: dict) -> Anchors:
    sections: set[str] = set()
    by_placement: dict[str, frozenset[str]] = {}
    for section in (body or {}).get("sections") or []:
        if section.get("ref"):
            sections.add(section["ref"])
        for placement in section.get("placements") or []:
            if placement.get("ref"):
                by_placement[placement["ref"]] = frozenset(
                    b["ref"] for b in placement.get("bullets") or [] if b.get("ref")
                )
    return Anchors(
        bank={
            "entry_id": frozenset(entry["id"] for entry in entries),
            "bullet_id": frozenset(
                bullet["id"] for entry in entries for bullet in entry.get("bullets") or []
            ),
        },
        sections=frozenset(sections),
        bullet_refs_by_placement=by_placement,
    )


def _text(value: Any, limit: int) -> Optional[str]:
    if value is None:
        return None
    out = str(value).strip()
    if not out or out.lower() in {"null", "none", "n/a"}:
        return None
    return out[:limit]


def _int(value: Any) -> Optional[int]:
    # `isinstance(True, int)` is true, and a stray `true` becoming bank entry 1
    # is the one wrong id that would pass validation.
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _position(value: Any) -> Optional[int]:
    index = _int(value)
    return None if index is None else max(0, index)


def _normalize_op(entry: Any) -> dict[str, Any]:
    # Not a dict becomes an unnamed operation rather than vanishing here, so
    # `_validate_ops` stays the only place a suggestion is dropped and the
    # count it reports is the whole count.
    data = entry if isinstance(entry, dict) else {}
    return {
        "op": _text(data.get("op"), 40) or "",
        "accepted": True,
        "rationale": _text(data.get("rationale"), MAX_RATIONALE_CHARS),
        "entry_id": _int(data.get("entry_id")),
        "bullet_id": _int(data.get("bullet_id")),
        "section": _text(data.get("section"), MAX_LABEL_CHARS),
        "section_id": _text(data.get("section_id"), MAX_REF_CHARS),
        "label": _text(data.get("label"), MAX_LABEL_CHARS),
        "placement_id": _text(data.get("placement_id"), MAX_REF_CHARS),
        "bullet_ref": _text(data.get("bullet_ref"), MAX_REF_CHARS),
        "position": _position(data.get("position")),
        "text": _text(data.get("text"), MAX_RAW_TEXT_CHARS),
    }


def _normalize_ops(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, (list, tuple)):
        return []
    return [_normalize_op(entry) for entry in raw[:MAX_OPS]]


def _rejection(op: dict[str, Any], anchors: Anchors) -> Optional[str]:
    name = op["op"]
    shape = OP_SHAPES.get(name)
    if shape is None:
        return f"{name or 'an unnamed operation'} is not an operation a proposal may use"

    if shape.bank_field:
        value = op[shape.bank_field]
        if value not in anchors.bank[shape.bank_field]:
            return f"{name} names {shape.bank_field} {value!r}, which is not in the bank"
    if shape.placement and op["placement_id"] not in anchors.bullet_refs_by_placement:
        return f"{name} names placement {op['placement_id']!r}, which is not in this draft"
    if shape.bullet_ref and op["bullet_ref"] not in anchors.bullet_refs_by_placement.get(
        op["placement_id"], ()
    ):
        return f"{name} names bullet {op['bullet_ref']!r}, which is not in that entry"
    if shape.section_id and op["section_id"] not in anchors.sections:
        return f"{name} names section {op['section_id']!r}, which is not in this draft"
    if shape.label and not op["label"]:
        return f"{name} does not say what to rename the section to"
    if shape.text:
        if not op["text"]:
            return f"{name} has no replacement text"
        if len(op["text"]) > MAX_BULLET_CHARS:
            return f"{name} is longer than the {MAX_BULLET_CHARS} characters a bullet can be"
    return None


def _validate_ops(
    ops: list[dict[str, Any]], anchors: Anchors
) -> tuple[list[dict[str, Any]], list[str]]:
    kept: list[dict[str, Any]] = []
    rejected: list[str] = []
    for op in ops:
        reason = _rejection(op, anchors)
        if reason is None:
            kept.append(op)
        else:
            rejected.append(reason)
    return kept, rejected


def _kind(value: Any) -> str:
    candidate = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    # An unrecognised kind fails `models.BankEntryCreate` on the way out, which
    # would turn a salvageable record into a 500.
    return candidate if candidate in bank.ENTRY_KINDS else "experience"


def _bullet_texts(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    texts = [text for text in (_text(item, MAX_BULLET_CHARS) for item in value) if text]
    return texts[:MAX_IMPORT_BULLETS]


def _normalize_entries(data: Any) -> list[dict[str, Any]]:
    raw = data.get("entries") if isinstance(data, dict) else data
    if not isinstance(raw, (list, tuple)):
        return []

    entries: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title"), bank.MAX_TITLE_LENGTH)
        if not title:
            continue
        entries.append(
            {
                "kind": _kind(item.get("kind")),
                "title": title,
                "organization": _text(item.get("organization"), 300),
                "location": _text(item.get("location"), 200),
                "start_date": _text(item.get("start_date"), 40),
                "end_date": _text(item.get("end_date"), 40),
                "is_current": bool(item.get("is_current")),
                "url": _text(item.get("url"), 1000),
                "detail": _text(item.get("detail"), 600),
                "bullets": _bullet_texts(item.get("bullets")),
            }
        )
    return entries[:MAX_IMPORT_ENTRIES]


def _post_for(draft: dict[str, Any]) -> dict[str, Any]:
    post_id = draft.get("job_post_id")
    if post_id is None:
        raise ValueError(
            "This draft is not linked to a job post. Tailoring needs the advertisement to "
            "tailor towards."
        )
    try:
        post = jobposts.get_post(post_id)
    except jobposts.JobPostNotFound as exc:
        raise ValueError(str(exc)) from exc
    if not (post.get("raw_text") or "").strip():
        raise ValueError(
            "This draft's job post has no advertisement text yet. Paste or fetch it before tailoring."
        )
    return post


def _post_block(post: dict[str, Any]) -> str:
    header = [f"Title: {post['title']}"]
    if post.get("organization"):
        header.append(f"Organization: {post['organization']}")
    body = str(post.get("raw_text") or "")[:MAX_POST_CHARS]
    return "\n".join(header) + "\n\nAdvertisement:\n" + body


def _keyword_block(post: dict[str, Any]) -> str:
    grouped: dict[str, list[str]] = {}
    for keyword in post.get("keywords") or []:
        term = str(keyword.get("term") or "").strip()
        if term:
            grouped.setdefault(str(keyword.get("bucket") or "technical"), []).append(term)
    lines = [
        f"{label}: {', '.join(grouped[bucket])}"
        for bucket, label in BUCKET_LABELS.items()
        if grouped.get(bucket)
    ]
    return "\n".join(lines) or "No keywords have been extracted from this advertisement yet."


def _coverage_block(report: dict[str, Any]) -> str:
    rows = report.get("keywords") or []
    if not rows:
        return "No coverage has been measured for this draft."
    missing = [row["term"] for row in rows if not row.get("covered")]
    lines = [f"The draft already uses {report.get('covered', 0)} of {report.get('total', 0)} terms."]
    if missing:
        lines.append(
            "Terms the draft does not yet use: "
            + ", ".join(missing)
            + ". Use one only where an existing bullet genuinely supports it."
        )
    return "\n".join(lines)


def _draft_block(body: dict) -> str:
    lines: list[str] = []
    for section in (body or {}).get("sections") or []:
        lines.append(f"Section {section.get('ref')}: {section.get('label')}")
        for placement in section.get("placements") or []:
            heading = " -- ".join(
                part
                for part in (
                    placement.get("title"),
                    placement.get("organization"),
                    placement.get("dates"),
                )
                if part
            )
            lines.append(f"  Placement {placement.get('ref')}: {heading}")
            for bullet in placement.get("bullets") or []:
                lines.append(f"    Bullet {bullet.get('ref')}: {bullet.get('text')}")
    return "\n".join(lines) or "The draft is empty."


def _within(lines: list[str], budget: int) -> str:
    """Whole lines only. Half an inventory line invites a half-guessed id."""
    kept: list[str] = []
    for line in lines:
        budget -= len(line) + 1
        if budget < 0:
            break
        kept.append(line)
    return "\n".join(kept)


def _bank_block(entries: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for entry in entries:
        heading = " -- ".join(
            part
            for part in (entry.get("title"), entry.get("organization"), bank.format_dates(entry))
            if part
        )
        lines.append(f"Entry {entry['id']} ({entry.get('kind')}): {heading}")
        if entry.get("detail"):
            lines.append(f"  Detail: {entry['detail']}")
        for bullet in entry.get("bullets") or []:
            lines.append(f"  Bullet {bullet['id']}: {bullet.get('text')}")
    return _within(lines, MAX_BANK_CHARS) or "The bank is empty."


def _prompt(
    post: dict[str, Any],
    coverage: dict[str, Any],
    draft: dict[str, Any],
    entries: list[dict[str, Any]],
) -> str:
    return (
        f"{_post_block(post)}\n\n"
        f"Terms this advertisement screens on:\n{_keyword_block(post)}\n\n"
        f"Coverage as the draft stands:\n{_coverage_block(coverage)}\n\n"
        f"Current draft '{draft['name']}':\n{_draft_block(draft['body'])}\n\n"
        f"The student's experience bank, every record you may draw on:\n{_bank_block(entries)}"
    )


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _summary(data: Any, *, kept: int, dropped: int) -> str:
    written = _text(data.get("summary"), MAX_SUMMARY_CHARS) if isinstance(data, dict) else None
    noun = "change" if kept == 1 else "changes"
    parts = [written or f"{kept} {noun} proposed for this advertisement."]
    if dropped:
        discarded = "suggestion" if dropped == 1 else "suggestions"
        parts.append(
            f"Discarded {dropped} {discarded} that named experience, wording or a position this "
            "bank and draft do not have."
        )
    return "\n\n".join(parts)


def _nothing_usable(rejected: list[str]) -> str:
    """An empty proposal would read as "nothing here needs improving", which is
    a different and much more flattering claim than the one that is true.
    """
    if not rejected:
        return (
            "The tailoring pass did not suggest any changes to this draft. Check that the job post "
            "has the full advertisement text."
        )
    noun = "change" if len(rejected) == 1 else "changes"
    return (
        f"Every one of the {len(rejected)} suggested {noun} named experience, wording or a position "
        "this bank and draft do not have, so there is nothing to review. Add the experience to the "
        "bank and tailor again."
    )


def propose_tailoring(draft_id: int, *, model: Optional[str] = None) -> dict[str, Any]:
    """Build and store a 'tailor' proposal. Returns the proposal dict."""
    draft = drafts.get_draft(draft_id)
    post = _post_for(draft)
    entries = bank.list_entries()
    anchors = _anchors(entries, draft["body"])
    if not entries and not anchors.bullet_refs_by_placement:
        raise ValueError(
            "There is nothing to tailor yet: the experience bank is empty and so is this draft. "
            "Import a resume into the bank first."
        )

    prompt = _prompt(post, drafts.coverage_report(draft_id), draft, entries)

    try:
        data = extract_json(
            run_claude(prompt, system=TAILOR_SYSTEM_PROMPT, model=model, timeout=TAILOR_TIMEOUT)
        )
    except (ClaudeCallError, ValueError) as exc:
        raise TailorError(f"Could not tailor this draft: {exc}") from exc

    ops = _normalize_ops(data.get("operations") if isinstance(data, dict) else data)
    kept, rejected = _validate_ops(ops, anchors)
    if rejected:
        logger.warning(
            "Dropped %d of %d tailoring operations for draft %s: %s",
            len(rejected), len(ops), draft_id, "; ".join(rejected),
        )
    if not kept:
        raise TailorError(_nothing_usable(rejected))

    summary = _summary(data, kept=len(kept), dropped=len(rejected))
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO draft_proposals (draft_id, kind, status, summary, operations, created_at)
               VALUES (?, 'tailor', 'pending', ?, ?, ?)""",
            (draft_id, summary, json.dumps(kept), _now()),
        )
        proposal_id = int(cursor.lastrowid)

    logger.info(
        "Tailored draft %s against job post %s: %d operations offered, %d dropped",
        draft_id, post["id"], len(kept), len(rejected),
    )
    return drafts.get_proposal(proposal_id)


def import_bank_from_resume(text: str, *, model: Optional[str] = None) -> dict[str, Any]:
    """Turn an existing resume's plain text into proposed bank records."""
    source = (text or "").strip()
    if not source:
        raise ValueError("Paste the text of a resume to import records from.")

    try:
        data = extract_json(
            run_claude(
                f"Resume:\n{source[:MAX_IMPORT_CHARS]}",
                system=IMPORT_SYSTEM_PROMPT,
                model=model,
                timeout=IMPORT_TIMEOUT,
            )
        )
    except (ClaudeCallError, ValueError) as exc:
        raise TailorError(f"Could not read that resume: {exc}") from exc

    entries = _normalize_entries(data)
    if not entries:
        raise TailorError(
            "No resume records could be read out of that text. Paste the body of the resume, "
            "sections and bullets included."
        )

    logger.info(
        "Read %d records and %d bullets out of %d characters of resume text",
        len(entries), sum(len(entry["bullets"]) for entry in entries), len(source),
    )
    return {"entries": entries}
