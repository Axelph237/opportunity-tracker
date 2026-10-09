"""Named regions of a LaTeX document that the composer is allowed to rewrite.

The document is the resume. Nothing here generates one: a slot marks a stretch
of source the composer may replace, and everything outside every slot is the
user's, untouched, forever.

Two rules make that safe to rely on.

Writing is opt-in per slot. `write` splices only the slots it is handed new
content for, so a document whose slots nobody edited comes back byte for byte.

Anything a slot holds that the block grammar does not recognise survives as an
opaque block: it can be moved and removed, it is written back exactly as it
was read, and it is never reformatted. A hand-written flourish inside a slot
is therefore safe from the composer even though the composer owns the region.

The markers are LaTeX comments by default, so a document carrying them still
compiles anywhere with no package to install. Their shape is a setting, since
a user who prefers an environment or a no-op macro should be able to say so.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from database import get_setting, set_setting
from latex import strip_latex

SETTING_KEY = "slot_markers"

# `{name}` is where the slot's name goes. Comments, so TeX ignores the whole
# line and the document is portable.
DEFAULT_MARKERS = {"open": "% <<slot {name}>>", "close": "% <</slot>>"}

NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,60}")


class SlotError(ValueError):
    """The document's markers do not describe regions we can act on."""


@dataclass
class Slot:
    """One region, and where it sits in the source."""

    name: str
    # Offsets of the body, between the two marker lines. Writing replaces
    # exactly this span, so the markers themselves always survive.
    start: int
    end: int

    @property
    def key(self) -> str:
        return self.name.strip().lower()


@dataclass
class Block:
    """One item inside a slot.

    `raw` is what was read, and what is written back when nothing changed.
    `kind` is "opaque" for anything the grammar did not recognise, which is
    the whole reason an unparseable line is not a lost line.
    """

    kind: str
    raw: str
    heading: Optional[str] = None
    args: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    # Whether this sat inside the entry list. Tracked so a line written
    # outside it comes back outside it: re-emitting everything inside would
    # quietly move someone's own LaTeX into an itemize.
    in_list: bool = True

    def as_dict(self) -> dict[str, Any]:
        """Both forms of the text, deliberately.

        `args` and `bullets` are the LaTeX, which is what gets written back
        and must survive untouched. The `_text` pairs are the same thing as
        the page reads it, because a canvas showing `38\\%` and `\\textbf{x}`
        is showing the user the markup rather than their resume.
        """
        return {
            "kind": self.kind,
            "raw": self.raw,
            "heading": self.heading,
            "args": list(self.args),
            "bullets": list(self.bullets),
            "args_text": [strip_latex(arg) for arg in self.args],
            "bullets_text": [strip_latex(text) for text in self.bullets],
            "in_list": self.in_list,
        }


def markers() -> dict[str, str]:
    stored = get_setting(SETTING_KEY)
    if not stored:
        return dict(DEFAULT_MARKERS)
    try:
        data = json.loads(stored)
    except (TypeError, ValueError):
        return dict(DEFAULT_MARKERS)
    shape = {
        "open": str(data.get("open") or DEFAULT_MARKERS["open"]),
        "close": str(data.get("close") or DEFAULT_MARKERS["close"]),
    }
    # A pattern with nowhere to put the name would match every slot at once.
    if "{name}" not in shape["open"]:
        shape["open"] = DEFAULT_MARKERS["open"]
    return shape


def save_markers(payload: Any) -> dict[str, str]:
    data = payload if isinstance(payload, dict) else {}
    shape = {
        "open": str(data.get("open") or "").strip() or DEFAULT_MARKERS["open"],
        "close": str(data.get("close") or "").strip() or DEFAULT_MARKERS["close"],
    }
    if "{name}" not in shape["open"]:
        raise SlotError("The opening marker needs {name} in it, so a slot can be named.")
    if shape["open"].strip() == shape["close"].strip():
        raise SlotError("The opening and closing markers have to differ.")
    set_setting(SETTING_KEY, json.dumps(shape))
    return shape


def _patterns(shape: dict[str, str]) -> tuple[re.Pattern, re.Pattern]:
    """The two markers as line-anchored patterns, with the name captured."""
    head, _, tail = shape["open"].partition("{name}")
    opener = re.compile(
        rf"^[ \t]*{re.escape(head)}(?P<name>{NAME.pattern}?){re.escape(tail)}[ \t]*$",
        re.MULTILINE,
    )
    closer = re.compile(rf"^[ \t]*{re.escape(shape['close'])}[ \t]*$", re.MULTILINE)
    return opener, closer


def find(source: str, shape: Optional[dict[str, str]] = None) -> list[Slot]:
    """Every slot in the document, in the order it appears.

    Nesting is refused rather than guessed at: a slot inside a slot has two
    possible owners for the same text and no way to choose between them.
    """
    shape = shape or markers()
    opener, closer = _patterns(shape)
    source = source or ""

    events = [(m.start(), "open", m) for m in opener.finditer(source)]
    events += [(m.start(), "close", m) for m in closer.finditer(source)]
    events.sort(key=lambda pair: pair[0])

    found: list[Slot] = []
    pending: Optional[re.Match] = None
    for _, kind, match in events:
        if kind == "open":
            if pending is not None:
                raise SlotError(
                    f"Slot {match.group('name').strip()!r} opens before "
                    f"{pending.group('name').strip()!r} closes."
                )
            pending = match
            continue
        if pending is None:
            raise SlotError("A slot closes without having been opened.")
        name = pending.group("name").strip()
        if not name:
            raise SlotError("A slot has no name.")
        found.append(Slot(name=name, start=pending.end(), end=match.start()))
        pending = None

    if pending is not None:
        raise SlotError(f"Slot {pending.group('name').strip()!r} is never closed.")

    seen: set[str] = set()
    for slot in found:
        if slot.key in seen:
            raise SlotError(f"Two slots are both called {slot.name!r}.")
        seen.add(slot.key)
    return found


# The macros the composer understands. Anything else inside a slot is opaque.
_HEADING_ARITY = {"resumeSubheading": 4, "resumeProjectHeading": 2}
_ITEM_OPEN = r"\resumeItemListStart"
_ITEM_CLOSE = r"\resumeItemListEnd"
# The list a slot's entries live in. Inside the region rather than around
# it, because an `itemize` with no `\item` in it is a LaTeX error, so a slot
# that does not own its wrapper cannot be empty and a blank resume could not
# compile at all.
_WRAPPER = (r"\resumeSubHeadingListStart", r"\resumeSubHeadingListEnd")


def _balanced(source: str, start: int) -> tuple[Optional[str], int]:
    """The contents of the brace group at `start`, and where it ends.

    Counts depth rather than matching a pattern, because a bullet routinely
    contains braces of its own and a non-greedy match would stop at the first
    one it met.
    """
    if start >= len(source) or source[start] != "{":
        return None, start
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if char == "{" and (index == start or source[index - 1] != "\\"):
            depth += 1
        elif char == "}" and source[index - 1] != "\\":
            depth -= 1
            if depth == 0:
                return source[start + 1 : index], index + 1
    return None, start


def _args(source: str, start: int, count: int) -> tuple[Optional[list[str]], int]:
    """`count` brace groups in a row, skipping the whitespace between them."""
    found: list[str] = []
    cursor = start
    for _ in range(count):
        while cursor < len(source) and source[cursor] in " \t\r\n":
            cursor += 1
        value, cursor = _balanced(source, cursor)
        if value is None:
            return None, start
        found.append(value)
    return found, cursor


def parse(body: str) -> list[Block]:
    """A slot's contents as blocks, losing nothing.

    Text between recognised macros is kept as opaque blocks rather than
    dropped, so writing the same blocks back reproduces the slot.
    """
    blocks: list[Block] = []
    cursor = 0
    pending = 0  # where the current run of unrecognised text began
    # A body with no wrapper in it at all is a bare run of entries, which
    # belong in a list: that is what a freshly rendered record looks like.
    # A body that does have one is tracked precisely, so a line written
    # outside it stays outside.
    depth = {"in": not any(token in body for token in _WRAPPER)}

    def flush(upto: int) -> None:
        raw = body[pending:upto]
        if raw.strip():
            blocks.append(Block(kind="opaque", raw=raw, in_list=depth["in"]))

    while cursor < len(body):
        if body[cursor] != "\\":
            cursor += 1
            continue
        name_match = re.match(r"\\([A-Za-z@]+)", body[cursor:])
        if name_match is None:
            cursor += 1
            continue
        name = name_match.group(1)
        if "\\" + name in _WRAPPER:
            # Structural, and the composer's to re-emit. Kept out of the
            # blocks so reordering them cannot strand a list open.
            flush(cursor)
            depth["in"] = "\\" + name == _WRAPPER[0]
            cursor += name_match.end()
            pending = cursor
            continue
        arity = _HEADING_ARITY.get(name)
        if arity is None:
            cursor += name_match.end()
            continue
        args, after = _args(body, cursor + name_match.end(), arity)
        if args is None:
            cursor += name_match.end()
            continue

        bullets, after = _bullets(body, after)
        flush(cursor)
        blocks.append(
            Block(kind="entry", raw=body[cursor:after], heading=name, args=args,
                  bullets=bullets, in_list=depth["in"])
        )
        cursor = after
        pending = after

    flush(len(body))
    return blocks


def _bullets(body: str, start: int) -> tuple[list[str], int]:
    """The item list following a heading, if the next thing is one."""
    cursor = start
    while cursor < len(body) and body[cursor] in " \t\r\n":
        cursor += 1
    if not body.startswith(_ITEM_OPEN, cursor):
        return [], start
    cursor += len(_ITEM_OPEN)
    texts: list[str] = []
    while cursor < len(body):
        while cursor < len(body) and body[cursor] in " \t\r\n":
            cursor += 1
        if body.startswith(_ITEM_CLOSE, cursor):
            return texts, cursor + len(_ITEM_CLOSE)
        if not body.startswith(r"\resumeItem", cursor):
            # Something else is in the list. The heading keeps its bullets out
            # of it entirely rather than this guessing at where it ends.
            return [], start
        value, after = _balanced(body, cursor + len(r"\resumeItem"))
        if value is None:
            return [], start
        texts.append(value)
        cursor = after
    return [], start


def render(blocks: list[Block], *, indent: str = "  ") -> str:
    """Blocks back to LaTeX. An opaque block is reproduced, never reformatted."""
    def one(block: Block) -> str:
        if block.kind != "entry":
            return block.raw.strip("\n")
        lines = ["\\" + (block.heading or "") + "".join(f"{{{arg}}}" for arg in block.args)]
        if block.bullets:
            lines.append(_ITEM_OPEN)
            lines += [f"{indent}\\resumeItem{{{text}}}" for text in block.bullets]
            lines.append(_ITEM_CLOSE)
        return "\n".join(lines)

    # One pass, opening the list when a run of listed blocks starts and
    # closing it when the run ends. Order is preserved exactly, so a line
    # written outside the list is written back outside it, and a region with
    # nothing listed emits no list at all because an empty one will not
    # compile.
    out: list[str] = []
    listing = False
    for block in blocks:
        if block.in_list and not listing:
            out.append(_WRAPPER[0])
            listing = True
        elif not block.in_list and listing:
            out.append(_WRAPPER[1])
            listing = False
        out.append(one(block))
    if listing:
        out.append(_WRAPPER[1])
    return "\n".join(out)


def write(source: str, contents: dict[str, str], shape: Optional[dict[str, str]] = None) -> str:
    """Replace the body of each named slot, and nothing else.

    Keyed by slot name, so a caller that hands over nothing gets the document
    it gave us back, unchanged to the byte. Splicing runs from the end so the
    offsets of the slots before it stay valid.
    """
    if not contents:
        return source
    found = find(source, shape)
    wanted = {str(key).strip().lower(): value for key, value in contents.items()}
    unknown = wanted.keys() - {slot.key for slot in found}
    if unknown:
        raise SlotError(f"This document has no slot called {sorted(unknown)[0]!r}.")

    out = source
    for slot in sorted(found, key=lambda s: s.start, reverse=True):
        if slot.key not in wanted:
            continue
        body = wanted[slot.key].strip("\n")
        out = out[: slot.start] + "\n" + body + "\n" + out[slot.end :]
    return out


def read(source: str, shape: Optional[dict[str, str]] = None) -> list[dict[str, Any]]:
    """Every slot with its blocks, which is what the composer lays out."""
    return [
        {
            "name": slot.name,
            "key": slot.key,
            "blocks": [block.as_dict() for block in parse(source[slot.start : slot.end])],
        }
        for slot in find(source, shape)
    ]
