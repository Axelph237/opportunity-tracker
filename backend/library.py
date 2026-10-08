"""Every resume you have, however it came to exist.

Three things used to be called a resume and only two of them were ever listed
together. A draft composed on the canvas lived in one list, a document typed
by hand lived in another, and a draft that had been pushed was a row in both
with nothing saying they were the same resume.

This is the union, deduplicated by the link a draft holds to the instance it
was pushed into. One row per resume, carrying which halves of it exist.
"""

from __future__ import annotations

from typing import Any

import resumes
from database import get_db


def _row(
    *,
    instance_id: int | None,
    draft_id: int | None,
    name: str,
    updated_at: str | None,
    has_pdf: bool = False,
    is_default: bool = False,
    compile_ok: bool = False,
    linked_count: int = 0,
) -> dict[str, Any]:
    return {
        # Stable across a refresh and unique across both tables, which neither
        # id is on its own.
        "key": f"instance:{instance_id}" if instance_id is not None else f"draft:{draft_id}",
        "instance_id": instance_id,
        "draft_id": draft_id,
        "name": name,
        # What you can do with it. Composed means there are records behind it
        # and the canvas can open it; pushed means there is a document to
        # render, edit as source, score against or attach to a listing.
        "composed": draft_id is not None,
        "pushed": instance_id is not None,
        "has_pdf": has_pdf,
        "is_default": is_default,
        "compile_ok": compile_ok,
        "linked_count": linked_count,
        "updated_at": updated_at,
    }


def list_library() -> list[dict[str, Any]]:
    """Scored first, then most recently touched, the order Resumes already used."""
    with get_db() as conn:
        instances = conn.execute(
            """SELECT r.*, (
                   SELECT COUNT(*) FROM opportunities o WHERE o.resume_instance_id = r.id
               ) AS linked_count, (
                   SELECT d.id FROM resume_drafts d
                   WHERE d.resume_instance_id = r.id ORDER BY d.id LIMIT 1
               ) AS draft_id
               FROM resume_instances r"""
        ).fetchall()
        # Only the ones nothing has been pushed from. A draft with an instance
        # is already represented by it, under the same name.
        unpushed = conn.execute(
            """SELECT id, name, updated_at FROM resume_drafts
               WHERE resume_instance_id IS NULL"""
        ).fetchall()

    rows = [
        _row(
            instance_id=row["id"],
            draft_id=row["draft_id"],
            name=row["name"],
            updated_at=row["updated_at"],
            has_pdf=bool(row["pdf_filename"]) and resumes.pdf_path(dict(row)).is_file(),
            is_default=bool(row["is_default"]),
            compile_ok=bool(row["compile_ok"]),
            linked_count=row["linked_count"],
        )
        for row in instances
    ]
    rows += [
        _row(instance_id=None, draft_id=row["id"], name=row["name"], updated_at=row["updated_at"])
        for row in unpushed
    ]
    # Two passes because Python's sort is stable: the first settles ties
    # between rows touched in the same second, the second is the real order.
    rows.sort(key=lambda row: row["key"])
    rows.sort(key=lambda row: (row["is_default"], row["updated_at"] or ""), reverse=True)
    return rows
