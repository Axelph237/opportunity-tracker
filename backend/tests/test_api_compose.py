"""Composing by rewriting a region of the resume's own source.

There is no second structure kept in step with the document any more, so what
matters here is that editing a region leaves everything else exactly as the
user left it.
"""

from __future__ import annotations

import latex

# Captured at import, before conftest replaces the engine for every test.
_REAL_COMPILE = latex.compile_pdf
_REAL_AVAILABLE = latex.latex_available

DOC = r"""\documentclass{article}
\begin{document}
\section{Experience}
% <<slot experience>>
\resumeSubHeadingListStart
\resumeSubheading{Fermilab}{2026}{Intern}{Batavia, IL}
\resumeItemListStart
  \resumeItem{Calibrated the readout}
\resumeItemListEnd
\resumeSubHeadingListEnd
\hrule
% <</slot>>
Hand written prose nothing may touch.
% <<slot projects>>
% <</slot>>
\end{document}
"""


def resume_with(client, latex: str = DOC) -> int:
    made = client.post("/api/resumes", json={"name": "Slotted"}).json()
    client.patch(f"/api/resumes/{made['id']}", json={"latex": latex})
    return made["id"]


def entry_with(client, **overrides) -> dict:
    payload = {
        "kind": "experience",
        "title": "Research Assistant",
        "organization": "UChicago PME",
        "location": "Chicago, IL",
        "start_date": "Jun 2025",
        "is_current": True,
        "bullets": ["Cut epoch time 38% on a PyTorch pipeline"],
        **overrides,
    }
    return client.post("/api/bank/entries", json=payload).json()


def source_of(client, instance_id: int) -> str:
    return client.get(f"/api/resumes/{instance_id}").json()["latex"]


def slot_named(rows, name: str) -> dict:
    return next(row for row in rows if row["key"] == name)


# ------------------------------------------------------- placing a record

def test_placing_a_record_writes_it_into_the_document_itself(app_client):
    instance_id = resume_with(app_client)
    entry = entry_with(app_client)

    response = app_client.post(
        f"/api/resumes/{instance_id}/slots/experience/placements", json={"entry_id": entry["id"]}
    )

    assert response.status_code == 200, response.text
    source = source_of(app_client, instance_id)
    assert r"\resumeSubheading{UChicago PME}" in source
    assert r"\resumeItem{Cut epoch time 38\% on a PyTorch pipeline}" in source


def test_placing_a_record_leaves_the_rest_of_the_document_alone(app_client):
    """The whole argument for slots. Everything outside the region, and the
    other region, survive the edit."""
    instance_id = resume_with(app_client)
    entry = entry_with(app_client)

    app_client.post(f"/api/resumes/{instance_id}/slots/experience/placements",
                    json={"entry_id": entry["id"]})

    source = source_of(app_client, instance_id)
    assert "Hand written prose nothing may touch." in source
    assert r"\documentclass{article}" in source
    assert source.count("% <<slot ") == 2
    assert r"\resumeSubheading{Fermilab}{2026}{Intern}{Batavia, IL}" in source


def test_a_line_the_composer_cannot_read_survives_an_edit_to_its_region(app_client):
    """`\\hrule` is not in the grammar, so it rides along as an opaque block
    rather than being dropped on the first edit."""
    instance_id = resume_with(app_client)
    entry = entry_with(app_client)

    app_client.post(f"/api/resumes/{instance_id}/slots/experience/placements",
                    json={"entry_id": entry["id"]})

    assert r"\hrule" in source_of(app_client, instance_id)


def test_a_record_lands_where_it_was_dropped(app_client):
    instance_id = resume_with(app_client)
    entry = entry_with(app_client, title="Goes first")

    rows = app_client.post(f"/api/resumes/{instance_id}/slots/experience/placements",
                           json={"entry_id": entry["id"], "position": 0}).json()

    blocks = slot_named(rows, "experience")["blocks"]
    assert blocks[0]["args"][2] == "Goes first"


def test_placing_into_a_region_the_document_lacks_is_a_404(app_client):
    instance_id = resume_with(app_client)
    entry = entry_with(app_client)

    response = app_client.post(f"/api/resumes/{instance_id}/slots/education/placements",
                               json={"entry_id": entry["id"]})

    assert response.status_code == 404
    assert "no slot called" in response.json()["detail"]


# -------------------------------------------------------- rewriting a region

def test_writing_a_region_back_unchanged_changes_the_document_not_at_all(app_client):
    instance_id = resume_with(app_client)
    before = source_of(app_client, instance_id)
    blocks = slot_named(app_client.get(f"/api/resumes/{instance_id}/slots").json(), "experience")["blocks"]

    app_client.put(f"/api/resumes/{instance_id}/slots/experience", json={"blocks": blocks})

    assert source_of(app_client, instance_id) == before


def test_reordering_blocks_reorders_the_source(app_client):
    instance_id = resume_with(app_client)
    entry = entry_with(app_client, title="Second")
    rows = app_client.post(f"/api/resumes/{instance_id}/slots/experience/placements",
                           json={"entry_id": entry["id"]}).json()
    blocks = slot_named(rows, "experience")["blocks"]

    app_client.put(f"/api/resumes/{instance_id}/slots/experience",
                   json={"blocks": list(reversed(blocks))})

    source = source_of(app_client, instance_id)
    assert source.index("Second") < source.index("Intern")


def test_emptying_a_region_leaves_its_markers_and_the_document_around_it(app_client):
    instance_id = resume_with(app_client)

    app_client.put(f"/api/resumes/{instance_id}/slots/experience", json={"blocks": []})

    source = source_of(app_client, instance_id)
    assert "% <<slot experience>>" in source
    assert "Hand written prose nothing may touch." in source
    assert r"\resumeSubheading{Fermilab}" not in source


def test_a_document_whose_markers_do_not_pair_up_refuses_the_edit(app_client):
    instance_id = resume_with(app_client, latex="% <<slot experience>>\nx\n")

    response = app_client.put(f"/api/resumes/{instance_id}/slots/experience", json={"blocks": []})

    assert response.status_code == 409


# ------------------------------------------------------------- on the page

WRAPPED = r"""\documentclass[letterpaper,11pt]{article}
\usepackage{enumitem}
\newcommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=0pt, label={}]}
\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}}
\newcommand{\resumeItem}[1]{\item\small{#1}}
\newcommand{\resumeSubheading}[4]{\item \textbf{#1} \hfill #2 \\ \textit{\small #3}}
\begin{document}
% <<slot experience>>
% <</slot>>
\end{document}
"""


def test_an_empty_region_and_a_filled_one_both_compile(app_client, monkeypatch):
    """The slot owns its list. An `itemize` with no `\\item` does not compile,
    so a region that did not own its wrapper could never be emptied, and a
    blank resume could not be made at all."""
    import io

    import latex
    import pytest

    real_available = _REAL_AVAILABLE
    if not real_available():
        pytest.skip("no TeX engine on this machine")
    monkeypatch.setattr(latex, "latex_available", real_available)
    pypdf = pytest.importorskip("pypdf")

    instance_id = resume_with(app_client, latex=WRAPPED)
    entry = entry_with(app_client)
    app_client.post(f"/api/resumes/{instance_id}/slots/experience/placements",
                    json={"entry_id": entry["id"]})

    result = _REAL_COMPILE(source_of(app_client, instance_id), timeout=180)

    assert result.ok is True, result.log
    text = "".join(p.extract_text() for p in pypdf.PdfReader(io.BytesIO(result.pdf_bytes)).pages)
    assert "Research Assistant" in text
    assert "Cut epoch time 38%" in text
    assert "slot" not in text.lower()


# ------------------------------------------------- bringing drafts across

def test_a_draft_becomes_a_document_the_composer_can_read_back(app_client):
    """Drafts were the truth and LaTeX was generated from them. Converting one
    has to leave the same structure findable in the document itself."""
    entry = entry_with(app_client)
    draft = app_client.post("/api/drafts", json={"name": "Legacy"}).json()
    app_client.post(f"/api/drafts/{draft['id']}/placements", json={"entry_id": entry["id"]})

    adopted = app_client.post(f"/api/drafts/{draft['id']}/adopt")

    assert adopted.status_code == 200, adopted.text
    rows = app_client.get(f"/api/resumes/{adopted.json()['id']}/slots").json()
    assert [row["blocks"][0]["args"][2] for row in rows if row["blocks"]] == ["Research Assistant"]


def test_converting_writes_into_the_resume_the_draft_was_already_pushed_to(app_client):
    entry = entry_with(app_client)
    draft = app_client.post("/api/drafts", json={"name": "Legacy"}).json()
    app_client.post(f"/api/drafts/{draft['id']}/placements", json={"entry_id": entry["id"]})
    pushed = app_client.post(f"/api/drafts/{draft['id']}/push").json()["resume_instance_id"]

    adopted = app_client.post(f"/api/drafts/{draft['id']}/adopt").json()

    assert adopted["id"] == pushed
    assert "% <<slot " in adopted["latex"]


def test_converting_keeps_the_draft_so_a_bad_conversion_can_be_walked_away_from(app_client):
    draft = app_client.post("/api/drafts", json={"name": "Legacy"}).json()

    app_client.post(f"/api/drafts/{draft['id']}/adopt")

    assert app_client.get(f"/api/drafts/{draft['id']}").status_code == 200


def test_converting_a_draft_that_is_not_there_is_a_404(app_client):
    assert app_client.post("/api/drafts/4040/adopt").status_code == 404


def test_the_markers_a_conversion_writes_are_the_ones_configured(app_client):
    app_client.put("/api/slot-markers", json={"open": r"\slotbegin{{name}}", "close": r"\slotend"})
    entry = entry_with(app_client)
    draft = app_client.post("/api/drafts", json={"name": "Legacy"}).json()
    app_client.post(f"/api/drafts/{draft['id']}/placements", json={"entry_id": entry["id"]})

    adopted = app_client.post(f"/api/drafts/{draft['id']}/adopt").json()

    assert r"\slotbegin{" in adopted["latex"]
    assert "% <<slot " not in adopted["latex"]


def test_converting_points_the_draft_at_the_document_it_became(app_client):
    """Without the link the draft is converted and the composer still finds no
    document behind it, so it carries on editing the old body."""
    draft = app_client.post("/api/drafts", json={"name": "Legacy"}).json()

    adopted = app_client.post(f"/api/drafts/{draft['id']}/adopt").json()

    assert app_client.get(f"/api/drafts/{draft['id']}").json()["resume_instance_id"] == adopted["id"]


# ------------------------------------------------- starting from nothing

def test_a_blank_resume_opens_with_regions_to_compose_into(app_client):
    """Started from the user's own resume.tex instead, a new resume has no
    slots and the composer cannot touch it at all."""
    made = app_client.post("/api/resumes", json={"name": "Blank", "blank": True}).json()

    rows = app_client.get(f"/api/resumes/{made['id']}/slots").json()

    assert [row["key"] for row in rows] == ["experience", "education", "projects", "skills"]
    assert all(row["blocks"] == [] for row in rows)


def test_a_resume_not_asked_to_be_blank_still_starts_from_your_own(app_client, resume_tmp):
    app_client.post("/api/settings/resume-tex", json={"source": "\\documentclass{article}"})

    made = app_client.post("/api/resumes", json={"name": "Mine"}).json()

    assert "% <<slot " not in made["latex"]


def test_a_blank_resume_can_be_composed_into_straight_away(app_client):
    made = app_client.post("/api/resumes", json={"name": "Blank", "blank": True}).json()
    entry = entry_with(app_client)

    placed = app_client.post(f"/api/resumes/{made['id']}/slots/experience/placements",
                             json={"entry_id": entry["id"]})

    assert placed.status_code == 200, placed.text
    assert slot_named(placed.json(), "experience")["blocks"][0]["args"][2] == "Research Assistant"


def test_a_blank_resume_compiles_before_anything_is_put_in_it(app_client, monkeypatch):
    """Four empty regions, and an `itemize` with no `\\item` does not compile,
    which is what makes the slot own its list rather than sit inside one."""
    import pytest

    if not _REAL_AVAILABLE():
        pytest.skip("no TeX engine on this machine")
    import latex as latex_module

    monkeypatch.setattr(latex_module, "latex_available", _REAL_AVAILABLE)
    made = app_client.post("/api/resumes", json={"name": "Blank", "blank": True}).json()

    result = _REAL_COMPILE(made["latex"], timeout=180)

    assert result.ok is True, result.log


def test_converting_an_empty_draft_gives_a_resume_that_can_be_composed(app_client):
    """It renders to a document with no sections and so no regions, which
    would convert it into a resume the composer cannot touch."""
    draft = app_client.post("/api/drafts", json={"name": "Never used"}).json()

    adopted = app_client.post(f"/api/drafts/{draft['id']}/adopt").json()

    rows = app_client.get(f"/api/resumes/{adopted['id']}/slots").json()
    assert [row["key"] for row in rows] == ["experience", "education", "projects", "skills"]
