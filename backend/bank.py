"""The experience bank: reusable records a resume draft composes from.

`ENTRY_KINDS` is the single source of truth for what a bank entry can be and
how it renders. Keeping it here rather than as a SQL CHECK or a chain of `if
kind == ...` is what stops the renderer, the validator and the UI from each
growing their own copy of the list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
