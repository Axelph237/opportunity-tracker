"""Turning a draft's structured body into the LaTeX a resume template expects.

Pure on purpose: no database, no filesystem, no subprocess. A renderer that
reached for any of those could only be exercised with a TeX distribution
installed, and this is the half of the builder that runs on every edit.

Which macro an entry heads with, and whether its bullets itemize, come from
`bank.ENTRY_KINDS`. Nothing here branches on `kind`: a new kind is a row in
that registry, and a renderer that grew its own `elif` chain would be a second
copy of the list to keep in sync.
"""

from __future__ import annotations

from typing import Any, Callable

import bank
from bank import KindLayout

# The one substitution point a resume template offers. Chosen over appending to
# the end of the document because a template without it is a template the user
# has not told us where to write into.
BODY_MARKER = "%%RESUME-BODY%%"

# The ten characters TeX reads as instructions rather than text. Applied with
# `str.translate`, which walks the original string once, so the backslashes the
# replacements introduce are never re-escaped.
_ESCAPE_TABLE = str.maketrans(
    {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
)

# A URL is an argument hyperref reads mostly verbatim, so it needs far less
# than prose does. Escaping `_` or `~` there would corrupt the address.
_URL_TABLE = str.maketrans(
    {
        "\\": r"\%5C",
        "{": r"\%7B",
        "}": r"\%7D",
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
    }
)


def escape(text: Any) -> str:
    """Plain text to LaTeX-safe text."""
    return str(text if text is not None else "").translate(_ESCAPE_TABLE)


def escape_url(url: Any) -> str:
    """An address safe to hand to `\\href` as its first argument."""
    return str(url if url is not None else "").translate(_URL_TABLE)


def _field(placement: dict, name: str) -> str:
    return escape(placement.get(name) or "")


def _titled(placement: dict) -> str:
    """The entry's title, linked when it has a URL."""
    title = _field(placement, "title")
    url = (placement.get("url") or "").strip()
    if not url:
        return title
    return rf"\href{{{escape_url(url)}}}{{{title}}}"


def _heading_subheading(placement: dict) -> str:
    return (
        r"\resumeSubheading"
        f"{{{_field(placement, 'organization')}}}"
        f"{{{_field(placement, 'dates')}}}"
        f"{{{_titled(placement)}}}"
        f"{{{_field(placement, 'location')}}}"
    )


def _heading_project(placement: dict) -> str:
    label = rf"\textbf{{{_titled(placement)}}}"
    detail = _field(placement, "detail")
    if detail:
        label = rf"{label} $|$ \emph{{{detail}}}"
    return rf"\resumeProjectHeading{{{label}}}{{{_field(placement, 'dates')}}}"


def _heading_plain(placement: dict) -> str:
    return rf"\resumeProjectHeading{{\textbf{{{_titled(placement)}}}}}{{{_field(placement, 'dates')}}}"


_HEADINGS: dict[str, Callable[[dict], str]] = {
    "subheading": _heading_subheading,
    "project": _heading_project,
    "plain": _heading_plain,
}


def _bullet_texts(placement: dict) -> list[str]:
    bullets = placement.get("bullets") or []
    return [escape(b.get("text")) for b in bullets if (b.get("text") or "").strip()]


def _body_bullets(placement: dict, layout: KindLayout) -> str:
    lines = [_HEADINGS[layout.heading](placement)]
    texts = _bullet_texts(placement)
    if texts:
        # An `itemize` holding no `\item` is a TeX error, so an entry whose
        # bullets were all dropped prints its heading and stops there.
        lines.append(r"\resumeItemListStart")
        lines.extend(rf"\resumeItem{{{text}}}" for text in texts)
        lines.append(r"\resumeItemListEnd")
    return "\n".join(lines)


def _body_inline(placement: dict, _layout: KindLayout) -> str:
    """One labelled, comma-joined row, how a skills block reads on a resume.

    The `\\item` is not decoration: the enclosing list is an `itemize`, and
    text placed in one before any `\\item` is a TeX error.
    """
    terms = ", ".join(_bullet_texts(placement))
    label = rf"\textbf{{{_titled(placement)}}}"
    return rf"\item \small{{{label}{{: {terms}}}}}" if terms else rf"\item \small{{{label}}}"


_BODIES: dict[str, Callable[[dict, KindLayout], str]] = {
    "bullets": _body_bullets,
    "inline": _body_inline,
}


def render_section(section: dict) -> str:
    """One `\\section` and its entries, or nothing at all when it holds none.

    An empty section is dropped rather than emitted: the wrapper is an
    `itemize`, and an empty one fails the compile that would have shown the
    user a resume with a stray blank heading.
    """
    rendered = []
    for placement in section.get("placements") or []:
        layout = bank.layout_for(placement.get("kind"))
        block = _BODIES[layout.bullet_style](placement, layout)
        if block.strip():
            rendered.append(block)
    if not rendered:
        return ""
    return "\n".join(
        [
            rf"\section{{{escape(section.get('label'))}}}",
            r"\resumeSubHeadingListStart",
            *rendered,
            r"\resumeSubHeadingListEnd",
        ]
    )


def render_body(body: dict) -> str:
    """The whole draft as the LaTeX that replaces the template's body marker."""
    sections = [render_section(section) for section in (body or {}).get("sections") or []]
    return "\n\n".join(section for section in sections if section.strip())


def render_document(template: str, body: dict) -> str:
    """The draft placed inside the user's own preamble and heading block."""
    source = template or ""
    if BODY_MARKER not in source:
        raise ValueError(
            f"The resume template has no {BODY_MARKER} marker, so there is nowhere "
            "to put the draft. Add the marker where the body belongs."
        )
    # The first marker is where the body belongs. Replacing all of them would
    # print the whole resume once per marker; the ones left behind are LaTeX
    # comments and cost the document nothing.
    return source.replace(BODY_MARKER, render_body(body), 1)
