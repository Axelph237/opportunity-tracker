"""The shipped template and the renderer as one contract.

`test_resume_render.py` compiles the renderer's output against a preamble
written inside that test file. That proved the renderer self-consistent and
said nothing about the template every install actually gets, which is how a
default `resume_template` defining none of the renderer's macros shipped. These
tests drive the real seeded setting instead.

`REAL_COMPILE` and `ENGINE_AVAILABLE` are captured at import time, before
conftest's autouse guards replace `latex.compile_pdf` and force
`latex_available` to False.
"""

from __future__ import annotations

import re

import pytest

import bank
import database
import latex
import resume_render

REAL_COMPILE = latex.compile_pdf
REAL_AVAILABLE = latex.latex_available
ENGINE_AVAILABLE = REAL_AVAILABLE()

# The renderer's own macro vocabulary. Anything outside this family is either
# plain LaTeX or comes from a package the template loads.
RENDERER_MACRO = re.compile(r"\\(resume[A-Za-z]*)")


def every_kind_body() -> dict:
    """One placement per registry kind, so no heading style goes unrendered."""
    return {
        "sections": [
            {
                "ref": f"s{index}",
                "label": layout.default_section,
                "placements": [
                    {
                        "ref": f"p{index}",
                        "entry_id": index,
                        "kind": kind,
                        "title": "A title",
                        "organization": "An organization",
                        "location": "Chicago, IL",
                        "dates": "Jun 2026 -- Sep 2026",
                        "detail": "Python",
                        "url": "https://example.org/x",
                        "bullets": [{"ref": f"b{index}", "text": "Did the thing"}],
                    }
                ],
            }
            for index, (kind, layout) in enumerate(bank.ENTRY_KINDS.items())
        ]
    }


def test_the_shipped_template_defines_every_macro_the_renderer_emits():
    """The TeX-free half of the contract, so a machine with no engine still
    catches a template and a renderer drifting apart."""
    emitted = set(RENDERER_MACRO.findall(resume_render.render_body(every_kind_body())))
    defined = set(RENDERER_MACRO.findall(
        " ".join(re.findall(r"\\newcommand\{(\\resume[A-Za-z]*)\}", database.RESUME_TEMPLATE))
    ))

    assert emitted, "the sample body rendered no renderer macros at all"
    assert emitted <= defined, f"undefined in the template: {sorted(emitted - defined)}"


def seed_a_draft(app_client) -> int:
    """A draft holding one record of every kind, composed the way the UI does."""
    draft_id = app_client.post("/api/drafts", json={"name": "Tailored"}).json()["id"]
    for kind, layout in bank.ENTRY_KINDS.items():
        entry = app_client.post("/api/bank/entries", json={
            "kind": kind,
            "title": "Delphi" if kind == "project" else "Research Assistant",
            "organization": "Argonne National Laboratory",
            "location": "Lemont, IL",
            "start_date": "Jun 2026",
            "end_date": "Sep 2026",
            "url": "https://github.com/me/delphi" if kind == "project" else None,
            "detail": "Python, PyTorch" if kind == "project" else None,
            "bullets": (
                ["Python", "C++", "Rust"] if layout.bullet_style == "inline"
                else ["Cut tree depth 38% on the hot path", "Shipped it"]
            ),
        }).json()
        placed = app_client.post(f"/api/drafts/{draft_id}/placements",
                                 json={"entry_id": entry["id"]})
        assert placed.status_code == 201, placed.text
    return draft_id


@pytest.mark.skipif(not ENGINE_AVAILABLE, reason="no TeX engine on this machine")
def test_a_pushed_draft_compiles_through_the_seeded_template(app_client, monkeypatch):
    """The whole product in one assertion: compose, push, compile what was
    written. A template that defines none of the renderer's macros fails here
    with `Undefined control sequence`, which is what every install got."""
    monkeypatch.setattr(latex, "latex_available", REAL_AVAILABLE)
    assert database.get_setting("resume_template") == database.RESUME_TEMPLATE
    draft_id = seed_a_draft(app_client)

    pushed = app_client.post(f"/api/drafts/{draft_id}/push")
    assert pushed.status_code == 200, pushed.text
    source = pushed.json()["latex"]

    result = REAL_COMPILE(source, timeout=180)

    assert result.ok is True, result.log
    assert result.errors == [], result.errors
    assert result.pdf_bytes.startswith(b"%PDF")
