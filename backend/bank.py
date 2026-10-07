"""The experience bank: reusable records a resume draft composes from.

`ENTRY_KINDS` is the single source of truth for what a bank entry can be and
how it renders. Keeping it here rather than as a SQL CHECK or a chain of `if
kind == ...` is what stops the renderer, the validator and the UI from each
growing their own copy of the list.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from database import get_db

EntryKind = Literal["education", "experience", "project", "skill_group",
                    "award", "publication", "presentation", "certification"]

BulletStyle = Literal["bullets", "inline"]   # "inline" renders terms comma-joined on one line


@dataclass(frozen=True)
class KindLayout:
    kind: str
    default_section: str     # the \section{} label this kind lands under by default
    bullet_style: BulletStyle
    heading: Literal["subheading", "project", "plain"]   # which LaTeX macro the header uses


ENTRY_KINDS: dict[str, KindLayout] = {
    "education": KindLayout("education", "Education", "bullets", "subheading"),
    "experience": KindLayout("experience", "Experience", "bullets", "subheading"),
    "project": KindLayout("project", "Projects", "bullets", "project"),
    "skill_group": KindLayout("skill_group", "Skills", "inline", "plain"),
    "award": KindLayout("award", "Honors and Awards", "bullets", "plain"),
    "publication": KindLayout("publication", "Publications", "bullets", "plain"),
    "presentation": KindLayout("presentation", "Presentations", "bullets", "plain"),
    "certification": KindLayout("certification", "Certifications", "bullets", "plain"),
}

# What an unrecognised kind lays out as. A draft snapshots the kind it was
# composed with, so a kind retired from the registry would otherwise make a
# resume the user already sent unrenderable.
FALLBACK_LAYOUT = KindLayout("", "Experience", "bullets", "plain")


def layout_for(kind: str | None) -> KindLayout:
    """The registry row a placement of this kind renders through."""
    return ENTRY_KINDS.get(kind or "", FALLBACK_LAYOUT)


MAX_TITLE_LENGTH = 200


class BankNotFound(LookupError):
    """Raised when an entry or bullet id does not exist."""


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def format_dates(entry: dict[str, Any]) -> str:
    """The single date string a placement prints.

    Resolved when an entry is placed, not when the draft renders: the draft
    snapshots what it showed the user, and a date recomputed at render time
    would be a value that changes with no write to the draft.
    """
    start = (entry.get("start_date") or "").strip()
    end = "Present" if entry.get("is_current") else (entry.get("end_date") or "").strip()
    if start and end:
        return f"{start} -- {end}"
    return start or end


def bullet_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def entry_dict(row: sqlite3.Row, bullets: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    data = dict(row)
    data["is_current"] = bool(data.get("is_current"))
    data["bullets"] = bullets or []
    return data


EDITABLE_FIELDS = (
    "kind", "title", "organization", "location",
    "start_date", "end_date", "is_current", "url", "detail",
)


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise whatever the caller wants written.

    `kind` is checked against the registry here rather than by a SQL CHECK, so
    the one list of kinds stays the one list of kinds.
    """
    changes = {key: value for key, value in values.items() if key in EDITABLE_FIELDS}
    if "kind" in changes and changes["kind"] not in ENTRY_KINDS:
        known = ", ".join(sorted(ENTRY_KINDS))
        raise ValueError(f"'{changes['kind']}' is not a kind of bank entry. Use one of: {known}.")
    if "title" in changes:
        title = (changes["title"] or "").strip()[:MAX_TITLE_LENGTH]
        if not title:
            raise ValueError("A bank entry needs a title.")
        changes["title"] = title
    if "is_current" in changes:
        changes["is_current"] = int(bool(changes["is_current"]))
    return changes


def _bullets_of(conn: sqlite3.Connection, entry_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    if not entry_ids:
        return {}
    placeholders = ",".join("?" * len(entry_ids))
    rows = conn.execute(
        f"SELECT * FROM bank_bullets WHERE entry_id IN ({placeholders}) ORDER BY position, id",
        entry_ids,
    ).fetchall()
    grouped: dict[int, list[dict[str, Any]]] = {entry_id: [] for entry_id in entry_ids}
    for row in rows:
        grouped[row["entry_id"]].append(bullet_dict(row))
    return grouped


def _write_order(conn: sqlite3.Connection, table: str, ids: list[int]) -> None:
    for position, row_id in enumerate(ids):
        conn.execute(f"UPDATE {table} SET position = ? WHERE id = ?", (position, row_id))


def list_entries() -> list[dict[str, Any]]:
    """Every record in the bank, in the order the user arranged it."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM bank_entries ORDER BY position, id").fetchall()
        grouped = _bullets_of(conn, [row["id"] for row in rows])
    return [entry_dict(row, grouped.get(row["id"])) for row in rows]


def get_entry(entry_id: int) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM bank_entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            raise BankNotFound(f"Bank entry {entry_id} not found")
        grouped = _bullets_of(conn, [entry_id])
    return entry_dict(row, grouped.get(entry_id))


def create_entry(values: dict[str, Any]) -> dict[str, Any]:
    """Add a record. Its bullets travel with it so an import confirms in one call."""
    changes = _clean(values)
    if not changes.get("kind"):
        raise ValueError("A bank entry needs a kind.")
    if not changes.get("title"):
        raise ValueError("A bank entry needs a title.")
    texts = [text.strip() for text in values.get("bullets") or [] if (text or "").strip()]

    with get_db() as conn:
        tail = conn.execute("SELECT COALESCE(MAX(position), -1) AS p FROM bank_entries").fetchone()["p"]
        columns = ", ".join(changes)
        marks = ", ".join("?" * len(changes))
        cursor = conn.execute(
            f"INSERT INTO bank_entries ({columns}, position, created_at, updated_at) "
            f"VALUES ({marks}, ?, ?, ?)",
            [*changes.values(), tail + 1, _now(), _now()],
        )
        entry_id = int(cursor.lastrowid)
        for position, text in enumerate(texts):
            conn.execute(
                "INSERT INTO bank_bullets (entry_id, text, position, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (entry_id, text, position, _now(), _now()),
            )
    return get_entry(entry_id)


def update_entry(entry_id: int, values: dict[str, Any]) -> dict[str, Any]:
    changes = _clean(values)
    if not changes:
        return get_entry(entry_id)
    with get_db() as conn:
        if conn.execute("SELECT 1 FROM bank_entries WHERE id = ?", (entry_id,)).fetchone() is None:
            raise BankNotFound(f"Bank entry {entry_id} not found")
        assignments = ", ".join(f"{column} = ?" for column in changes)
        conn.execute(
            f"UPDATE bank_entries SET {assignments}, updated_at = ? WHERE id = ?",
            [*changes.values(), _now(), entry_id],
        )
    return get_entry(entry_id)


def delete_entry(entry_id: int) -> None:
    """Remove a record. Drafts that placed it keep their snapshot and still render."""
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM bank_entries WHERE id = ?", (entry_id,))
        if cursor.rowcount == 0:
            raise BankNotFound(f"Bank entry {entry_id} not found")


def reorder(ids: list[int]) -> list[dict[str, Any]]:
    """Rewrite every entry's position in one transaction.

    Ids the caller left out keep their relative order behind the ones it named,
    and ids that no longer exist are dropped, so a stale rail still produces a
    total order rather than a 404 or a set of colliding positions.
    """
    with get_db() as conn:
        existing = [row["id"] for row in conn.execute(
            "SELECT id FROM bank_entries ORDER BY position, id"
        )]
        known = set(existing)
        named = [entry_id for entry_id in dict.fromkeys(ids) if entry_id in known]
        rest = [entry_id for entry_id in existing if entry_id not in set(named)]
        _write_order(conn, "bank_entries", named + rest)
    return list_entries()


def get_bullet(bullet_id: int) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM bank_bullets WHERE id = ?", (bullet_id,)).fetchone()
    if row is None:
        raise BankNotFound(f"Bank bullet {bullet_id} not found")
    return bullet_dict(row)


def create_bullet(entry_id: int, text: str, position: Optional[int] = None) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("A bullet needs some text.")
    with get_db() as conn:
        if conn.execute("SELECT 1 FROM bank_entries WHERE id = ?", (entry_id,)).fetchone() is None:
            raise BankNotFound(f"Bank entry {entry_id} not found")
        siblings = [row["id"] for row in conn.execute(
            "SELECT id FROM bank_bullets WHERE entry_id = ? ORDER BY position, id", (entry_id,)
        )]
        cursor = conn.execute(
            "INSERT INTO bank_bullets (entry_id, text, position, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (entry_id, cleaned, len(siblings), _now(), _now()),
        )
        bullet_id = int(cursor.lastrowid)
        if position is not None:
            siblings.insert(max(0, min(position, len(siblings))), bullet_id)
            _write_order(conn, "bank_bullets", siblings)
    return get_bullet(bullet_id)


def update_bullet(bullet_id: int, values: dict[str, Any]) -> dict[str, Any]:
    """Change a bullet's wording, its place among its siblings, or both.

    Editing the text here is what a draft's drift check measures against: the
    draft keeps its own snapshot, and the difference is what a sync proposal
    offers to reconcile.
    """
    text = values.get("text")
    position = values.get("position")
    with get_db() as conn:
        row = conn.execute("SELECT * FROM bank_bullets WHERE id = ?", (bullet_id,)).fetchone()
        if row is None:
            raise BankNotFound(f"Bank bullet {bullet_id} not found")
        if text is not None:
            cleaned = text.strip()
            if not cleaned:
                raise ValueError("A bullet needs some text.")
            conn.execute(
                "UPDATE bank_bullets SET text = ?, updated_at = ? WHERE id = ?",
                (cleaned, _now(), bullet_id),
            )
        if position is not None:
            siblings = [r["id"] for r in conn.execute(
                "SELECT id FROM bank_bullets WHERE entry_id = ? AND id != ? ORDER BY position, id",
                (row["entry_id"], bullet_id),
            )]
            siblings.insert(max(0, min(position, len(siblings))), bullet_id)
            _write_order(conn, "bank_bullets", siblings)
    return get_bullet(bullet_id)


def delete_bullet(bullet_id: int) -> None:
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM bank_bullets WHERE id = ?", (bullet_id,))
        if cursor.rowcount == 0:
            raise BankNotFound(f"Bank bullet {bullet_id} not found")
