"""Named regions of a LaTeX document, and what the composer may do to them.

The document is the resume now, so the thing worth proving is not that these
produce nice LaTeX. It is that they leave alone everything they were not
asked to touch.
"""

from __future__ import annotations

import io

import pytest

import latex
import slots

DOC = r"""\documentclass{article}
\begin{document}
\section{Experience}
% <<slot experience>>
\resumeSubheading{UChicago PME}{Jun 2025 -- Present}{Research Assistant}{Chicago, IL}
\resumeItemListStart
  \resumeItem{Cut epoch time 38\% on a \textbf{PyTorch} pipeline}
  \resumeItem{Built data ingestion on Kubernetes}
\resumeItemListEnd
% <</slot>>
\section{By hand}
Nothing in here is the composer's business.
% <<slot projects>>
\resumeProjectHeading{\textbf{Delphi}}{2026}
% <</slot>>
\end{document}
"""


def body_of(source: str, name: str) -> str:
    slot = next(s for s in slots.find(source) if s.key == name)
    return source[slot.start : slot.end]


# ------------------------------------------------------------------- finding

def test_every_slot_is_found_in_the_order_it_appears(db_path):
    assert [slot.name for slot in slots.find(DOC)] == ["experience", "projects"]


def test_a_document_with_no_slots_has_none(db_path):
    assert slots.find(r"\documentclass{article}\begin{document}x\end{document}") == []


@pytest.mark.parametrize("broken,complaint", [
    ("% <<slot a>>\nx\n", "never closed"),
    ("x\n% <</slot>>\n", "without having been opened"),
    ("% <<slot a>>\n% <<slot b>>\nx\n% <</slot>>\n% <</slot>>\n", "opens before"),
    ("% <<slot a>>\n% <</slot>>\n% <<slot A>>\n% <</slot>>\n", "both called"),
])
def test_markers_that_do_not_describe_a_region_are_refused(db_path, broken, complaint):
    """Guessing at what a malformed pair meant is how a document gets eaten."""
    with pytest.raises(slots.SlotError, match=complaint):
        slots.find(broken)


# ------------------------------------------------------------------- reading

def test_a_heading_and_its_bullets_read_as_one_block(db_path):
    blocks = slots.parse(body_of(DOC, "experience"))

    assert [block.kind for block in blocks] == ["entry"]
    assert blocks[0].heading == "resumeSubheading"
    assert blocks[0].args[2] == "Research Assistant"
    assert blocks[0].bullets == [
        r"Cut epoch time 38\% on a \textbf{PyTorch} pipeline",
        r"Built data ingestion on Kubernetes",
    ]


def test_a_bullet_keeps_the_braces_inside_it(db_path):
    """Matching to the first closing brace would cut `\\textbf{PyTorch}` in half."""
    blocks = slots.parse(body_of(DOC, "experience"))

    assert blocks[0].bullets[0].endswith(r"\textbf{PyTorch} pipeline")


def test_anything_the_grammar_does_not_know_survives_as_an_opaque_block(db_path):
    """The whole reason a hand-written line inside a slot is not a lost line."""
    blocks = slots.parse("\\hrule\n\\vspace{4pt}\n")

    assert [block.kind for block in blocks] == ["opaque"]
    assert blocks[0].raw.strip() == "\\hrule\n\\vspace{4pt}"


def test_a_heading_with_too_few_arguments_is_opaque_rather_than_guessed_at(db_path):
    blocks = slots.parse(r"\resumeSubheading{only}{two}")

    assert [block.kind for block in blocks] == ["opaque"]


# ------------------------------------------------------------------- writing

def test_writing_nothing_returns_the_document_unchanged(db_path):
    """Every guarantee here rests on this one."""
    assert slots.write(DOC, {}) == DOC


def test_reading_a_slot_and_writing_it_straight_back_changes_nothing(db_path):
    out = slots.write(DOC, {"experience": slots.render(slots.parse(body_of(DOC, "experience")))})

    assert out == DOC


def test_writing_one_slot_leaves_the_other_and_the_prose_between_them_alone(db_path):
    out = slots.write(DOC, {"experience": r"\resumeItem{Replaced}"})

    assert r"\resumeItem{Replaced}" in out
    assert "Nothing in here is the composer's business." in out
    assert r"\resumeProjectHeading{\textbf{Delphi}}{2026}" in out
    assert out.count("% <<slot experience>>") == 1


def test_the_markers_themselves_are_never_written_over(db_path):
    out = slots.write(DOC, {"experience": "", "projects": ""})

    assert out.count("% <<slot ") == 2
    assert out.count("% <</slot>>") == 2


def test_writing_both_slots_keeps_the_second_one_where_it_was(db_path):
    """Splicing front to back would shift every offset after the first edit."""
    out = slots.write(DOC, {"experience": "A", "projects": "B"})

    assert body_of(out, "experience").strip() == "A"
    assert body_of(out, "projects").strip() == "B"


def test_a_slot_the_document_does_not_have_is_refused(db_path):
    with pytest.raises(slots.SlotError, match="no slot called"):
        slots.write(DOC, {"education": "x"})


# ------------------------------------------------------------- marker format

def test_the_markers_are_a_setting_so_another_shape_can_be_used(db_path):
    slots.save_markers({"open": r"\slotbegin{{name}}", "close": r"\slotend"})
    source = "\\slotbegin{skills}\nx\n\\slotend\n"

    assert [slot.name for slot in slots.find(source)] == ["skills"]
    # And the default shape stops being recognised, which is the point.
    assert slots.find(DOC) == []


def test_an_opening_marker_with_nowhere_to_put_the_name_is_refused(db_path):
    with pytest.raises(slots.SlotError, match="needs .name."):
        slots.save_markers({"open": "% slot", "close": "% end"})


def test_markers_that_cannot_be_told_apart_are_refused(db_path):
    with pytest.raises(slots.SlotError, match="have to differ"):
        slots.save_markers({"open": "% {name}", "close": "% {name}"})


def test_a_stored_shape_that_will_not_parse_falls_back_to_the_default(db_path):
    import database

    database.set_setting(slots.SETTING_KEY, "{not json")

    assert slots.markers() == slots.DEFAULT_MARKERS


# -------------------------------------------------------------- over the api

SLOTTED = r"""\documentclass{article}
\begin{document}
% <<slot experience>>
\resumeSubheading{Fermilab}{2026}{Intern}{Batavia, IL}
% <</slot>>
\end{document}
"""


def test_a_document_reports_the_slots_the_composer_may_touch(app_client):
    made = app_client.post("/api/resumes", json={"name": "Slotted"}).json()
    app_client.patch(f"/api/resumes/{made['id']}", json={"latex": SLOTTED})

    rows = app_client.get(f"/api/resumes/{made['id']}/slots")

    assert rows.status_code == 200, rows.text
    assert [row["name"] for row in rows.json()] == ["experience"]
    assert rows.json()[0]["blocks"][0]["args"][0] == "Fermilab"


def test_a_document_with_no_slots_reports_none_rather_than_failing(app_client):
    made = app_client.post("/api/resumes", json={"name": "Plain"}).json()
    app_client.patch(f"/api/resumes/{made['id']}", json={"latex": "\\documentclass{article}"})

    assert app_client.get(f"/api/resumes/{made['id']}/slots").json() == []


def test_markers_that_do_not_pair_up_are_reported_rather_than_guessed_at(app_client):
    """A 409 because the document is in a state the composer cannot act on,
    not a 500 and not a silent empty list that looks like "no slots"."""
    made = app_client.post("/api/resumes", json={"name": "Broken"}).json()
    app_client.patch(f"/api/resumes/{made['id']}", json={"latex": "% <<slot a>>\nx\n"})

    response = app_client.get(f"/api/resumes/{made['id']}/slots")

    assert response.status_code == 409
    assert "never closed" in response.json()["detail"]


def test_the_marker_shape_round_trips_through_the_api(app_client):
    saved = app_client.put("/api/slot-markers",
                           json={"open": r"\slotbegin{{name}}", "close": r"\slotend"})

    assert saved.status_code == 200, saved.text
    assert app_client.get("/api/slot-markers").json() == saved.json()


def test_a_marker_shape_with_no_name_in_it_is_a_400(app_client):
    response = app_client.put("/api/slot-markers", json={"open": "% slot", "close": "% end"})

    assert response.status_code == 400


# Captured at import, before conftest's autouse guards replace the engine and
# force `latex_available` to False for every test.
REAL_COMPILE = latex.compile_pdf
REAL_AVAILABLE = latex.latex_available
ENGINE_AVAILABLE = REAL_AVAILABLE()


@pytest.mark.skipif(not ENGINE_AVAILABLE, reason="no TeX engine on this machine")
def test_a_document_carrying_markers_still_compiles_and_never_prints_them(db_path, monkeypatch):
    """The portability argument for comments, measured rather than asserted.
    A marker TeX did not ignore would end up on the page."""
    monkeypatch.setattr(latex, "latex_available", REAL_AVAILABLE)
    pypdf = pytest.importorskip("pypdf")
    source = (
        "\\documentclass{article}\n\\begin{document}\n"
        "% <<slot experience>>\nResearch Assistant at Fermilab\n% <</slot>>\n"
        "\\end{document}\n"
    )

    result = REAL_COMPILE(source, timeout=180)

    assert result.ok is True, result.log
    text = "".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(result.pdf_bytes)).pages)
    assert "Research Assistant at Fermilab" in text
    assert "slot" not in text.lower()


def test_a_block_carries_the_text_as_the_page_reads_it(db_path):
    """The canvas shows this pair. Showing the raw LaTeX would put `38\\%` and
    `\\textbf{...}` in front of the user instead of their resume."""
    block = slots.parse(
        "\\resumeSubheading{UChicago PME}{Jun 2025}{Research Assistant}{Chicago, IL}\n"
        "\\resumeItemListStart\n"
        "  \\resumeItem{Cut epoch time 38\\% on a \\textbf{PyTorch} pipeline}\n"
        "\\resumeItemListEnd"
    )[0].as_dict()

    assert block["bullets"][0] == "Cut epoch time 38\\% on a \\textbf{PyTorch} pipeline"
    assert block["bullets_text"][0] == "Cut epoch time 38% on a PyTorch pipeline"
    # The raw pair is what gets written back, so it must survive untouched.
    assert block["args"][0] == "UChicago PME"
