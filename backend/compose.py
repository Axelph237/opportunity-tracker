"""Editing a resume by rearranging the slots in its own source.

The document is the resume. There is no second structure held beside it and
kept in step, which is what made pushing, divergence and detaching necessary
before: the composer reads the source, changes a region of it, and writes the
source back.

Everything here goes through `slots.write`, so the guarantee that holds there
holds here. A region nobody edited is returned byte for byte, and anything
inside an edited region that the block grammar did not recognise is put back
exactly as it was read.
"""

from __future__ import annotations

from typing import Any, Optional

import bank
import resume_render
import resumes
import slots


class ComposeError(ValueError):
    """The request names something the document does not have."""


def _source(instance_id: int) -> str:
    return resumes.get_instance(instance_id)["latex"] or ""


def _save(instance_id: int, source: str) -> list[dict[str, Any]]:
    resumes.update_instance(instance_id, {"latex": source})
    return slots.read(source)


def read(instance_id: int) -> list[dict[str, Any]]:
    return slots.read(_source(instance_id))


def _blocks_of(source: str, key: str) -> tuple[slots.Slot, list[slots.Block]]:
    for slot in slots.find(source):
        if slot.key == key.strip().lower():
            return slot, slots.parse(source[slot.start : slot.end])
    raise ComposeError(f"This resume has no slot called {key!r}.")


def set_blocks(instance_id: int, key: str, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace one region with the blocks given, in the order given.

    An opaque block is carried by its `raw` alone. That is how a block the
    composer cannot read is still something the composer can move: it is
    reordered as a unit and written back untouched.
    """
    source = _source(instance_id)
    slot, _ = _blocks_of(source, key)
    rebuilt = [
        slots.Block(
            kind=str(block.get("kind") or "opaque"),
            raw=str(block.get("raw") or ""),
            heading=block.get("heading"),
            args=[str(arg) for arg in block.get("args") or []],
            bullets=[str(text) for text in block.get("bullets") or []],
            in_list=bool(block.get("in_list", True)),
        )
        for block in blocks
    ]
    return _save(instance_id, slots.write(source, {slot.key: slots.render(rebuilt)}))


def place_entry(
    instance_id: int, key: str, entry_id: int, *, position: Optional[int] = None
) -> list[dict[str, Any]]:
    """Put a bank record into a region, as the macros its kind calls for.

    Rendered through `resume_render` and read straight back with the slot
    parser, rather than built as a block directly. One path from a record to
    the page means the composer cannot drift from what actually prints.
    """
    source = _source(instance_id)
    slot, blocks = _blocks_of(source, key)

    entry = bank.get_entry(entry_id)
    rendered = resume_render.render_placement(bank.printable(entry))
    placed = slots.parse(rendered)
    if not placed:
        raise ComposeError(f"{entry.get('title') or 'That record'} has nothing to print.")

    at = len(blocks) if position is None else max(0, min(int(position), len(blocks)))
    blocks[at:at] = placed
    return _save(instance_id, slots.write(source, {slot.key: slots.render(blocks)}))


# ------------------------------------------------- starting from nothing

# What a blank resume opens with: named, empty, in the order a screener reads
# for them. Rename or delete any of them in the source afterwards; the
# composer follows whatever the document says.
BLANK_SECTIONS = ("Experience", "Education", "Projects", "Skills")


def blank_source() -> str:
    """A resume with nothing in it that is still composable.

    Starting a new resume from the user's own `resume.tex` hands them a
    document with no slots, which the composer cannot touch at all. This is
    the same preamble with empty regions cut into it.

    The slot holds the list as well as the entries, so an empty one is an
    empty region rather than an empty `itemize`, which does not compile.
    """
    import contact as contact_module
    from database import RESUME_TEMPLATE

    shape = slots.markers()
    body = "\n\n".join(
        "\n".join([
            rf"\section{{{label}}}",
            shape["open"].format(name=label.lower()),
            shape["close"],
        ])
        for label in BLANK_SECTIONS
    )
    return resume_render.fill(RESUME_TEMPLATE, body, contact_module.get_contact())


# ------------------------------------------------- bringing drafts across

def adopt_draft(draft_id: int) -> int:
    """Turn a draft into a slotted document, and hand back the resume it is.

    Drafts were the truth and LaTeX was generated from them. Converting one
    means rendering it the way a push always did, except with slot markers
    around each section's entries, so the composer can find the same
    structure in the document afterwards.

    The draft keeps its row. Nothing here deletes anything: a conversion that
    turned out wrong should be something the user can walk away from.
    """
    import contact as contact_module
    import drafts as drafts_module
    from database import get_setting

    draft = drafts_module.get_draft(draft_id)
    source = resume_render.render_document(
        get_setting("resume_template") or "",
        draft["body"],
        contact_module.get_contact(),
        slots.markers(),
    )

    instance_id = draft.get("resume_instance_id")
    if instance_id is None:
        instance_id = resumes.create_instance(draft["name"], latex_source=source)["id"]
        # Linked back, or the draft would be converted and the composer would
        # still find no document behind it and carry on editing the old body.
        drafts_module.attach_instance(draft_id, instance_id)
    else:
        resumes.update_instance(instance_id, {"latex": source})
    return instance_id
