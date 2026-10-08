"""The draft-to-LaTeX renderer, which is pure and therefore cheap to pin down.

`REAL_COMPILE` and `ENGINE_AVAILABLE` are captured at import time, before
conftest's autouse guards replace `latex.compile_pdf` with the "no test may run
a real engine" stub and force `latex_available` to False. Only the one
integration test at the bottom uses them; every other test here needs no TeX at
all, which is the point of keeping this module free of IO.
"""

from __future__ import annotations

import pytest

import bank
import latex
import resume_render

REAL_COMPILE = latex.compile_pdf
REAL_AVAILABLE = latex.latex_available
ENGINE_AVAILABLE = REAL_AVAILABLE()


def placement(**overrides) -> dict:
    base = {
        "ref": "p1",
        "entry_id": 1,
        "kind": "experience",
        "title": "Research Assistant",
        "organization": "Argonne National Laboratory",
        "location": "Lemont, IL",
        "dates": "Jun 2026 -- Sep 2026",
        "detail": None,
        "url": None,
        "bullets": [],
    }
    base.update(overrides)
    return base


def bullets(*texts) -> list[dict]:
    return [{"ref": f"b{i}", "text": text} for i, text in enumerate(texts)]


def body(*placements, label="Experience") -> dict:
    return {"sections": [{"ref": "s1", "label": label, "placements": list(placements)}]}


def render(*placements, label="Experience") -> str:
    return resume_render.render_body(body(*placements, label=label))


# ------------------------------------------------------------------ escaping

def test_every_one_of_the_ten_tex_specials_survives_escaping():
    """Each of these means something to TeX. An unescaped one either vanishes
    from the page or takes the rest of the document with it."""
    assert resume_render.escape(r"\ & % $ # _ { } ~ ^") == (
        r"\textbackslash{} \& \% \$ \# \_ \{ \} \textasciitilde{} \textasciicircum{}"
    )


def test_escaping_does_not_re_escape_the_backslashes_it_introduces():
    """A naive chain of replacements turns `&` into `\\&` and then into
    `\\textbackslash{}&`, which prints the markup instead of the ampersand."""
    assert resume_render.escape("&") == r"\&"
    assert resume_render.escape("%") == r"\%"


def test_a_percent_in_a_bullet_is_escaped_rather_than_commenting_out_the_line():
    """The quantified-achievement case. An unescaped `%` would comment away the
    closing brace and everything after it."""
    rendered = render(placement(bullets=bullets("Cut tree depth 38% on the hot path")))

    assert r"\resumeItem{Cut tree depth 38\% on the hot path}" in rendered
    assert "38% on" not in rendered


def test_a_url_keeps_the_characters_that_are_part_of_the_address():
    """Escaping a URL the way prose is escaped would send the reader to an
    address that does not exist, so `_` and `~` stay as they are."""
    rendered = render(
        placement(kind="project", title="Oracle", url="https://example.org/~me/a_b")
    )

    assert r"\href{https://example.org/~me/a_b}" in rendered


def test_a_url_escapes_the_characters_tex_would_act_on():
    """`&` is the alignment tab. An unescaped one inside `\\href` ends the
    macro's argument early and takes the compile down, so a query string is
    enough to make a resume unbuildable."""
    rendered = render(
        placement(kind="project", title="Oracle",
                  url="https://jobs.example.org/apply?id=7&src=resume#top")
    )

    assert r"\href{https://jobs.example.org/apply?id=7\&src=resume\#top}" in rendered


def test_a_url_percent_encodes_the_characters_tex_cannot_hand_through():
    r"""`\{` reaches hyperref as a backslash and a brace, so the link it makes
    is an address that does not exist. The percent form survives, the way the
    backslash already does."""
    rendered = render(placement(kind="project", title="Oracle", url=r"https://ex.com/{a}\b"))

    assert r"\href{https://ex.com/\%7Ba\%7D\%5Cb}" in rendered


def test_an_en_dash_in_a_date_reaches_the_document_as_itself():
    """The date string is shown in the browser and written into the document,
    so it carries a real en dash rather than TeX's `--`. Measured against the
    shipped template, it compiles and extracts back out of the page."""
    rendered = render(placement(dates="Jun 2026 \u2013 Sep 2026"))

    assert "Jun 2026 \u2013 Sep 2026" in rendered


# ------------------------------------------------------- layout off the registry

def test_an_experience_fills_the_four_argument_subheading_in_the_right_order():
    """`\\resumeSubheading` is {org}{dates}{title}{location}. Swapping any pair
    compiles cleanly and prints a resume that says the wrong thing."""
    rendered = render(placement())

    assert (
        r"\resumeSubheading{Argonne National Laboratory}{Jun 2026 -- Sep 2026}"
        r"{Research Assistant}{Lemont, IL}" in rendered
    )


def test_a_project_with_a_url_wraps_its_title_in_href():
    rendered = render(
        placement(
            kind="project",
            title="Delphi",
            detail="Python, PyTorch",
            url="https://github.com/me/delphi",
        )
    )

    assert r"\resumeProjectHeading{\textbf{\href{https://github.com/me/delphi}{Delphi}}" in rendered
    assert r"$|$ \emph{Python, PyTorch}" in rendered


def test_a_project_without_a_detail_omits_the_separator():
    rendered = render(placement(kind="project", title="Delphi", detail=None))

    assert r"$|$" not in rendered
    assert r"\resumeProjectHeading{\textbf{Delphi}}" in rendered


def test_a_skill_group_renders_comma_joined_inline_and_never_as_bullets():
    rendered = render(
        placement(kind="skill_group", title="Languages", bullets=bullets("Python", "C++", "Rust")),
        label="Relevant Skills",
    )

    assert r"\textbf{Languages}{: Python, C++, Rust}" in rendered
    assert r"\resumeItem" not in rendered
    assert r"\resumeItemListStart" not in rendered


def test_an_inline_row_carries_an_item_because_its_wrapper_is_an_itemize():
    """Text inside `itemize` before any `\\item` is a hard TeX error, so the
    skills block would take the whole compile down without this."""
    rendered = render(placement(kind="skill_group", title="Tools", bullets=bullets("Git")))

    item_index = rendered.index(r"\item")
    assert item_index > rendered.index(r"\resumeSubHeadingListStart")
    assert item_index < rendered.index(r"\textbf{Tools}")


# What each kind has to print, spelled out rather than read back off
# `ENTRY_KINDS`. A loop that asks the registry what to expect agrees with the
# registry whatever the registry says, including a row that is wrong. The
# detail is what separates `plain` from `project`: both reach for
# `\resumeProjectHeading`, and without a detail in the fixture their output is
# identical, so the test could not tell them apart either.
EXPECTED_HEADING = {
    "education": r"\resumeSubheading{Argonne National Laboratory}{Jun 2026 -- Sep 2026}{Thing}{Lemont, IL}",
    "experience": r"\resumeSubheading{Argonne National Laboratory}{Jun 2026 -- Sep 2026}{Thing}{Lemont, IL}",
    "project": r"\resumeProjectHeading{\textbf{Thing} $|$ \emph{Python}}{Jun 2026 -- Sep 2026}",
    "skill_group": r"\item \small{\textbf{Thing}{: Did the thing}}",
    "award": r"\resumeProjectHeading{\textbf{Thing}}{Jun 2026 -- Sep 2026}",
    "publication": r"\resumeProjectHeading{\textbf{Thing}}{Jun 2026 -- Sep 2026}",
    "presentation": r"\resumeProjectHeading{\textbf{Thing}}{Jun 2026 -- Sep 2026}",
    "certification": r"\resumeProjectHeading{\textbf{Thing}}{Jun 2026 -- Sep 2026}",
}

INLINE_KINDS = {"skill_group"}


def test_every_kind_prints_the_heading_its_layout_calls_for():
    assert set(EXPECTED_HEADING) == set(bank.ENTRY_KINDS), "a new kind needs a line above"

    for kind, heading in EXPECTED_HEADING.items():
        rendered = render(
            placement(kind=kind, title="Thing", detail="Python", bullets=bullets("Did the thing"))
        )
        assert heading in rendered, kind
        if kind in INLINE_KINDS:
            assert r"\resumeItem{" not in rendered, kind
        else:
            assert r"\resumeItem{Did the thing}" in rendered, kind


def test_a_kind_the_registry_no_longer_knows_still_renders():
    """A draft snapshots the kind it was composed with. Retiring a kind must not
    make a resume the user already sent unopenable."""
    rendered = render(placement(kind="internship-2019", title="Intern"))

    assert r"\textbf{Intern}" in rendered


# -------------------------------------------------------------- empty structures

def test_an_entry_whose_bullets_were_all_dropped_emits_no_itemize():
    """`\\begin{itemize}` with nothing in it is a TeX error."""
    rendered = render(placement(bullets=[]))

    assert r"\resumeSubheading" in rendered
    assert r"\resumeItemListStart" not in rendered


def test_a_blank_bullet_does_not_become_an_empty_item():
    rendered = render(placement(bullets=[{"ref": "b0", "text": "   "}]))

    assert r"\resumeItemListStart" not in rendered


def test_an_empty_section_renders_nothing_at_all():
    """Not an empty `\\section` and not an empty list: the wrapper is an
    itemize, and an empty one fails the compile."""
    rendered = resume_render.render_body({"sections": [{"ref": "s1", "label": "Projects", "placements": []}]})

    assert rendered == ""


def test_an_empty_body_renders_the_empty_string():
    assert resume_render.render_body({"sections": []}) == ""


def test_a_section_with_entries_wraps_them_in_the_subheading_list():
    rendered = render(placement())

    assert rendered.startswith(r"\section{Experience}")
    assert r"\resumeSubHeadingListStart" in rendered
    assert rendered.endswith(r"\resumeSubHeadingListEnd")


def test_a_section_label_is_escaped_like_any_other_text():
    rendered = render(placement(), label="Research & Analysis")

    assert r"\section{Research \& Analysis}" in rendered


# -------------------------------------------------------------- whole documents

def test_the_body_replaces_the_marker_in_the_template():
    document = resume_render.render_document(
        "PREAMBLE\n%%RESUME-BODY%%\nEND", body(placement())
    )

    assert document.startswith("PREAMBLE\n")
    assert document.endswith("\nEND")
    assert "%%RESUME-BODY%%" not in document
    assert r"\resumeSubheading{Argonne National Laboratory}" in document


def test_a_second_marker_does_not_print_the_resume_twice():
    """A template someone pasted a marker into twice would otherwise carry two
    copies of every entry. The leftover marker is a comment and prints nothing."""
    document = resume_render.render_document(
        "%%RESUME-BODY%%\nMIDDLE\n%%RESUME-BODY%%", body(placement())
    )

    assert document.count(r"\resumeSubheading") == 1
    assert document.endswith("\nMIDDLE\n%%RESUME-BODY%%")


def test_a_template_with_no_body_marker_is_refused():
    """Appending to the end instead would produce a document the user never
    asked for, in a place they did not choose."""
    with pytest.raises(ValueError, match="%%RESUME-BODY%%"):
        resume_render.render_document(r"\documentclass{article}", body(placement()))


def test_a_draft_renders_to_exactly_these_lines():
    """The push path compares the render to what it last wrote, so anything the
    renderer reorders or respaces reads as a hand edit on every push. Asserting
    the render equals a second call cannot catch that, because a pure function
    agrees with itself. Pinning the lines can, and it is also the only place
    the item list wrapping the bullets is checked to be in the right place:
    `\\resumeItem` expands to `\\item`, which is legal nowhere else."""
    draft = body(
        placement(bullets=bullets("One", "Two")),
        placement(ref="p2", kind="project", title="Delphi", detail="Rust"),
    )

    assert resume_render.render_body(draft).split("\n") == [
        r"\section{Experience}",
        r"\resumeSubHeadingListStart",
        r"\resumeSubheading{Argonne National Laboratory}{Jun 2026 -- Sep 2026}"
        r"{Research Assistant}{Lemont, IL}",
        r"\resumeItemListStart",
        r"\resumeItem{One}",
        r"\resumeItem{Two}",
        r"\resumeItemListEnd",
        r"\resumeProjectHeading{\textbf{Delphi} $|$ \emph{Rust}}{Jun 2026 -- Sep 2026}",
        r"\resumeSubHeadingListEnd",
    ]


# ------------------------------------------------------------------ integration

# The macros `resume_render` targets. The user's own `resume.tex` is the
# sb2nov template and already defines every one of them; this preamble is the
# smallest document that does, so the compile below proves the renderer's
# output and nothing about anybody's particular preamble.
MACRO_PREAMBLE = r"""\documentclass[letterpaper,11pt]{article}
\usepackage[margin=0.75in]{geometry}
\usepackage{enumitem}
\usepackage{titlesec}
\usepackage[hidelinks]{hyperref}
\pagestyle{empty}
\titleformat{\section}{\large\scshape}{}{0pt}{}[\titlerule]
\newcommand{\resumeItem}[1]{\item\small{{#1}}}
\newcommand{\resumeSubheading}[4]{%
  \item\begin{tabular*}{0.97\textwidth}[t]{l@{\extracolsep{\fill}}r}
    \textbf{#1} & #2 \\ \textit{\small#3} & \textit{\small #4} \\
  \end{tabular*}}
\newcommand{\resumeProjectHeading}[2]{%
  \item\begin{tabular*}{0.97\textwidth}{l@{\extracolsep{\fill}}r}
    \small#1 & #2 \\
  \end{tabular*}}
\newcommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=0.15in, label={}]}
\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}}
\begin{document}
%%RESUME-BODY%%
\end{document}
"""

COMPILABLE_BODY = {
    "sections": [
        {
            "ref": "s1",
            "label": "Experience",
            "placements": [
                placement(bullets=bullets("Cut tree depth 38% on the hot path", "Shipped it")),
            ],
        },
        {
            "ref": "s2",
            "label": "Projects",
            "placements": [
                placement(
                    ref="p2",
                    kind="project",
                    title="Delphi",
                    detail="Python, PyTorch",
                    # The query string is the point: `&` is the alignment tab,
                    # and `\resumeProjectHeading` lays its argument out in a
                    # `tabular*` exactly as the user's own resume.tex does.
                    url="https://github.com/me/delphi?tab=readme&v=2",
                    bullets=bullets("Trained the model"),
                ),
            ],
        },
        {
            "ref": "s3",
            "label": "Relevant Skills",
            "placements": [
                placement(ref="p3", kind="skill_group", title="Languages",
                          bullets=bullets("Python", "C++", "Rust")),
            ],
        },
    ]
}


@pytest.mark.skipif(not ENGINE_AVAILABLE, reason="no TeX engine on this machine")
def test_a_rendered_draft_compiles_under_a_real_engine(monkeypatch):
    """The only test here that needs TeX. Everything the renderer emits has to
    be valid in the document position it lands in, and a missing `\\item` or an
    empty `itemize` is the kind of mistake no string assertion catches."""
    # `compile_pdf` consults `latex_available` itself, and conftest's guard has
    # already forced it to False for this test.
    monkeypatch.setattr(latex, "latex_available", REAL_AVAILABLE)
    source = resume_render.render_document(MACRO_PREAMBLE, COMPILABLE_BODY)

    result = REAL_COMPILE(source, timeout=180)

    assert result.ok is True, result.log
    assert result.errors == [], result.errors
    assert result.pdf_bytes.startswith(b"%PDF")
