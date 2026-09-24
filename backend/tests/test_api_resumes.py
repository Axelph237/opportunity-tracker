"""The /api/resumes surface: variants, compilation, linking and the PDF."""

from __future__ import annotations

import pytest

import latex
import resumes


# A one-page PDF is all the endpoint cares about; the bytes only need the header
# for a client to treat the response as a PDF.
FAKE_PDF = b"%PDF-1.4\nfake render\n%%EOF\n"


@pytest.fixture
def compiles(monkeypatch):
    """Make `compile_pdf` succeed, returning a fixed PDF."""
    def _ok(source, **_kwargs):
        return latex.CompileResult(
            ok=True, pdf_bytes=FAKE_PDF, log="Output written on resume.pdf", engine="tectonic"
        )

    monkeypatch.setattr(resumes.latex, "compile_pdf", _ok)
    return _ok


@pytest.fixture
def no_engine(monkeypatch):
    """The state of a machine with no TeX distribution installed."""
    def _missing(*_args, **_kwargs):
        raise latex.LatexUnavailable("No LaTeX engine found.")

    monkeypatch.setattr(resumes.latex, "compile_pdf", _missing)
    monkeypatch.setattr(latex, "compile_pdf", _missing)
    return _missing


@pytest.fixture
def fails_to_compile(monkeypatch):
    def _bad(source, **_kwargs):
        raise latex.LatexCompileError(
            "Undefined control sequence.",
            log="! Undefined control sequence.\nl.12 \\nope",
            errors=[{"line": 12, "message": "Undefined control sequence."}],
        )

    monkeypatch.setattr(resumes.latex, "compile_pdf", _bad)
    return _bad


def make_opportunity(client, title="Quantum Intern"):
    with __import__("database").get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO opportunities (title, organization, type, url)
               VALUES (?, 'ACME', 'internship', ?)""",
            (title, f"https://example.com/{title.replace(' ', '-')}"),
        )
        return int(cursor.lastrowid)


# ------------------------------------------------------------------------ CRUD

def test_the_list_starts_empty(app_client):
    assert app_client.get("/api/resumes").json() == []


def test_the_first_variant_created_becomes_the_default(app_client, resume_tmp):
    body = app_client.post("/api/resumes", json={"name": "Base"}).json()
    assert body["is_default"] is True
    assert body["name"] == "Base"
    # With nothing uploaded and nothing to copy, it opens on the starter template.
    assert "\\documentclass" in body["latex"]


def test_the_second_variant_does_not_steal_the_default(app_client, resume_tmp):
    app_client.post("/api/resumes", json={"name": "Base"})
    second = app_client.post("/api/resumes", json={"name": "Tailored"}).json()
    assert second["is_default"] is False


def test_a_new_variant_starts_from_the_uploaded_tex(app_client, resume_tmp, no_engine):
    source = r"\documentclass{article}\begin{document}Jane Doe\end{document}"
    app_client.put("/api/settings/resume-tex", json={"latex": source})
    assert app_client.post("/api/resumes", json={"name": "Base"}).json()["latex"] == source


def test_copy_from_duplicates_an_existing_variant(app_client, resume_tmp):
    base = app_client.post("/api/resumes", json={"name": "Base"}).json()
    app_client.patch(f"/api/resumes/{base['id']}", json={"latex": "% edited"})
    copy = app_client.post(
        "/api/resumes", json={"name": "For IBM", "copy_from": base["id"]}
    ).json()
    assert copy["latex"] == "% edited"
    assert copy["id"] != base["id"]


def test_copy_from_an_unknown_id_is_a_404(app_client, resume_tmp):
    assert app_client.post("/api/resumes", json={"name": "x", "copy_from": 9999}).status_code == 404


def test_a_duplicate_name_gets_a_counter_rather_than_an_error(app_client, resume_tmp):
    """Names are how variants are told apart in a dropdown, so two identical
    ones would be a trap — but refusing the request mid-flow is worse."""
    app_client.post("/api/resumes", json={"name": "Base"})
    assert app_client.post("/api/resumes", json={"name": "Base"}).json()["name"] == "Base 2"


def test_renaming_onto_another_variants_name_is_refused(app_client, resume_tmp):
    app_client.post("/api/resumes", json={"name": "Base"})
    other = app_client.post("/api/resumes", json={"name": "Tailored"}).json()
    response = app_client.patch(f"/api/resumes/{other['id']}", json={"name": "Base"})
    assert response.status_code == 409


def test_an_empty_name_is_refused(app_client, resume_tmp):
    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    assert app_client.patch(f"/api/resumes/{instance['id']}", json={"name": "  "}).status_code == 422


def test_editing_the_source_saves_it(app_client, resume_tmp):
    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    app_client.patch(f"/api/resumes/{instance['id']}", json={"latex": "% my resume"})
    assert app_client.get(f"/api/resumes/{instance['id']}").json()["latex"] == "% my resume"


def test_the_list_view_leaves_the_documents_out(app_client, resume_tmp):
    """A dozen variants times a full LaTeX document is megabytes for a sidebar
    that only shows names and dates."""
    app_client.post("/api/resumes", json={"name": "Base"})
    assert "latex" not in app_client.get("/api/resumes").json()[0]


def test_an_unknown_id_is_a_404(app_client):
    assert app_client.get("/api/resumes/404").status_code == 404
    assert app_client.patch("/api/resumes/404", json={"name": "x"}).status_code == 404
    assert app_client.delete("/api/resumes/404").status_code == 404
    assert app_client.post("/api/resumes/404/compile").status_code == 404


# ------------------------------------------------------------------- compiling

def test_a_successful_compile_records_the_render(app_client, resume_tmp, compiles):
    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    body = app_client.post(f"/api/resumes/{instance['id']}/compile").json()
    assert body["compile_ok"] is True
    assert body["has_pdf"] is True
    assert body["compiled_at"]


def test_a_failed_compile_is_a_200_carrying_the_errors(app_client, resume_tmp, fails_to_compile):
    """The editor needs the line numbers to point at the problem, so a document
    that does not build is a normal response rather than an HTTP error."""
    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    response = app_client.post(f"/api/resumes/{instance['id']}/compile")
    assert response.status_code == 200
    body = response.json()
    assert body["compile_ok"] is False
    assert body["compile_errors"] == [{"line": 12, "message": "Undefined control sequence."}]
    assert "Undefined control sequence" in body["compile_log"]


def test_a_missing_engine_is_a_503(app_client, resume_tmp, monkeypatch):
    def _no_engine(*_args, **_kwargs):
        raise latex.LatexUnavailable("No LaTeX engine found.")

    monkeypatch.setattr(resumes.latex, "compile_pdf", _no_engine)
    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    response = app_client.post(f"/api/resumes/{instance['id']}/compile")
    assert response.status_code == 503
    assert "No LaTeX engine" in response.json()["detail"]


def test_a_failed_recompile_keeps_the_last_good_pdf(app_client, resume_tmp, compiles, monkeypatch):
    """Losing the preview because of a half-typed macro would make the editor
    unusable; the last render stays until a better one replaces it."""
    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    app_client.post(f"/api/resumes/{instance['id']}/compile")

    def _bad(*_args, **_kwargs):
        raise latex.LatexCompileError("broken", log="", errors=[])

    monkeypatch.setattr(resumes.latex, "compile_pdf", _bad)
    body = app_client.post(f"/api/resumes/{instance['id']}/compile").json()
    assert body["compile_ok"] is False
    assert body["has_pdf"] is True
    assert app_client.get(f"/api/resumes/{instance['id']}/pdf").status_code == 200


# ------------------------------------------------------------------------- PDF

def test_the_pdf_is_served_inline_for_the_preview(app_client, resume_tmp, compiles):
    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    app_client.post(f"/api/resumes/{instance['id']}/compile")
    response = app_client.get(f"/api/resumes/{instance['id']}/pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.content == FAKE_PDF


def test_download_sends_an_attachment_named_after_the_variant(app_client, resume_tmp, compiles):
    instance = app_client.post("/api/resumes", json={"name": "For IBM 2026"}).json()
    app_client.post(f"/api/resumes/{instance['id']}/compile")
    response = app_client.get(f"/api/resumes/{instance['id']}/pdf?download=true")
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment")
    assert "For-IBM-2026.pdf" in disposition


def test_asking_for_a_pdf_before_compiling_says_so(app_client, resume_tmp):
    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    response = app_client.get(f"/api/resumes/{instance['id']}/pdf")
    assert response.status_code == 404
    assert "compiled" in response.json()["detail"]


# -------------------------------------------------------------------- defaults

def test_making_a_variant_default_demotes_the_previous_one(app_client, resume_tmp, compiles):
    base = app_client.post("/api/resumes", json={"name": "Base"}).json()
    other = app_client.post("/api/resumes", json={"name": "Tailored"}).json()
    app_client.post(f"/api/resumes/{other['id']}/default")
    assert app_client.get(f"/api/resumes/{base['id']}").json()["is_default"] is False
    assert app_client.get(f"/api/resumes/{other['id']}").json()["is_default"] is True


def test_the_default_render_becomes_the_document_that_gets_scored(
    app_client, resume_tmp, compiles, monkeypatch
):
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        resumes,
        "publish_render",
        lambda pdf_bytes, text: captured.update(pdf=pdf_bytes, text=text),
    )
    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    app_client.post(f"/api/resumes/{instance['id']}/default")
    app_client.post(f"/api/resumes/{instance['id']}/compile")
    assert captured["pdf"] == FAKE_PDF


def test_compiling_a_non_default_variant_leaves_the_scored_document_alone(
    app_client, resume_tmp, compiles, monkeypatch
):
    """Tailoring a variant for one listing must not silently change what every
    other listing is scored against."""
    base = app_client.post("/api/resumes", json={"name": "Base"}).json()
    app_client.post(f"/api/resumes/{base['id']}/default")
    other = app_client.post("/api/resumes", json={"name": "Tailored"}).json()
    calls: list[object] = []
    monkeypatch.setattr(resumes, "publish_render", lambda pdf_bytes, text: calls.append(pdf_bytes))
    app_client.post(f"/api/resumes/{other['id']}/compile")
    assert calls == []


# -------------------------------------------------------------------- deletion

def test_deleting_a_variant_unlinks_its_listings_rather_than_deleting_them(
    app_client, resume_tmp
):
    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    opportunity_id = make_opportunity(app_client)
    app_client.patch(f"/api/opportunities/{opportunity_id}", json={"resume_instance_id": instance["id"]})

    app_client.delete(f"/api/resumes/{instance['id']}")

    listing = app_client.get(f"/api/opportunities/{opportunity_id}")
    assert listing.status_code == 200
    assert listing.json()["resume_instance_id"] is None


def test_deleting_the_default_promotes_another_variant(app_client, resume_tmp):
    """Something has to answer "which resume is this app scoring against"."""
    base = app_client.post("/api/resumes", json={"name": "Base"}).json()
    app_client.post(f"/api/resumes/{base['id']}/default")
    other = app_client.post("/api/resumes", json={"name": "Tailored"}).json()
    app_client.delete(f"/api/resumes/{base['id']}")
    assert app_client.get(f"/api/resumes/{other['id']}").json()["is_default"] is True


def test_deleting_the_last_variant_leaves_no_default(app_client, resume_tmp):
    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    app_client.delete(f"/api/resumes/{instance['id']}")
    assert app_client.get("/api/resumes").json() == []


def test_deleting_a_variant_removes_its_rendered_pdf(app_client, resume_tmp, compiles):
    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    app_client.post(f"/api/resumes/{instance['id']}/compile")
    artifact = resumes.RESUMES_DIR / f"resume-{instance['id']}.pdf"
    assert artifact.is_file()
    app_client.delete(f"/api/resumes/{instance['id']}")
    assert not artifact.exists()


# --------------------------------------------------------------------- linking

def test_a_listing_can_be_linked_to_a_variant(app_client, resume_tmp):
    instance = app_client.post("/api/resumes", json={"name": "For IBM"}).json()
    opportunity_id = make_opportunity(app_client)
    body = app_client.patch(
        f"/api/opportunities/{opportunity_id}", json={"resume_instance_id": instance["id"]}
    ).json()
    assert body["resume_instance_id"] == instance["id"]
    assert body["resume_instance_name"] == "For IBM"


def test_a_listing_can_be_unlinked_by_sending_null(app_client, resume_tmp):
    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    opportunity_id = make_opportunity(app_client)
    app_client.patch(f"/api/opportunities/{opportunity_id}", json={"resume_instance_id": instance["id"]})
    body = app_client.patch(
        f"/api/opportunities/{opportunity_id}", json={"resume_instance_id": None}
    ).json()
    assert body["resume_instance_id"] is None


def test_linking_to_a_variant_that_does_not_exist_is_a_404(app_client, resume_tmp):
    opportunity_id = make_opportunity(app_client)
    response = app_client.patch(
        f"/api/opportunities/{opportunity_id}", json={"resume_instance_id": 9999}
    )
    assert response.status_code == 404


def test_the_linked_endpoint_lists_the_listings_and_their_advice_state(app_client, resume_tmp):
    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    first = make_opportunity(app_client, "Quantum Intern")
    make_opportunity(app_client, "Unlinked Role")
    app_client.patch(f"/api/opportunities/{first}", json={"resume_instance_id": instance["id"]})

    linked = app_client.get(f"/api/resumes/{instance['id']}/linked").json()
    assert [row["title"] for row in linked] == ["Quantum Intern"]
    assert linked[0]["advice_generated_at"] is None


def test_the_list_view_counts_linked_listings(app_client, resume_tmp):
    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    for title in ("One", "Two"):
        app_client.patch(
            f"/api/opportunities/{make_opportunity(app_client, title)}",
            json={"resume_instance_id": instance["id"]},
        )
    assert app_client.get("/api/resumes").json()[0]["linked_count"] == 2


def test_listings_can_be_filtered_by_the_resume_linked_to_them(app_client, resume_tmp):
    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    linked = make_opportunity(app_client, "Linked Role")
    make_opportunity(app_client, "Other Role")
    app_client.patch(f"/api/opportunities/{linked}", json={"resume_instance_id": instance["id"]})

    rows = app_client.get(f"/api/opportunities?resume_instance_id={instance['id']}").json()
    assert [row["title"] for row in rows] == ["Linked Role"]


# ------------------------------------------------- the uploaded LaTeX source

SOURCE = r"""\documentclass{article}
\begin{document}
\section{Experience}
Built a quantum simulator in C++ at Quantum Labs, handling 30\% more qubits
than the previous implementation. Studied physics at the University of Chicago.
\end{document}
"""


def test_the_tex_source_starts_absent(app_client, resume_tmp):
    body = app_client.get("/api/settings/resume-tex").json()
    assert body["present"] is False
    assert body["latex"] is None


def test_saving_the_source_stores_it_on_disk(app_client, resume_tmp, no_engine):
    app_client.put("/api/settings/resume-tex", json={"latex": SOURCE})
    assert (resume_tmp / "resume.tex").read_text() == SOURCE
    body = app_client.get("/api/settings/resume-tex").json()
    assert body["present"] is True
    assert body["latex"] == SOURCE


def test_without_an_engine_the_stripped_text_is_what_gets_scored(app_client, resume_tmp, no_engine):
    """A machine with no TeX distribution should still score listings against
    the resume, just against its markup-stripped text rather than a render."""
    status = app_client.put("/api/settings/resume-tex", json={"latex": SOURCE}).json()
    assert status["loaded"] is True
    assert status["filename"] == "resume-active.txt"
    stored = (resume_tmp / "resume-active.txt").read_text()
    assert "Quantum Labs" in stored
    assert "\\documentclass" not in stored


def test_with_an_engine_the_render_is_what_gets_scored(app_client, resume_tmp, monkeypatch):
    import resume_loader

    monkeypatch.setattr(
        resume_loader, "render_tex_to_text", lambda source: (FAKE_PDF, "Rendered resume text")
    )
    status = app_client.put("/api/settings/resume-tex", json={"latex": SOURCE}).json()
    assert status["filename"] == "resume-active.pdf"
    assert (resume_tmp / "resume-active.pdf").read_bytes() == FAKE_PDF


def test_an_empty_source_is_refused(app_client, resume_tmp):
    assert app_client.put("/api/settings/resume-tex", json={"latex": "   "}).status_code == 400


def test_a_tex_file_can_be_uploaded_through_the_resume_endpoint(app_client, resume_tmp, no_engine):
    """The Settings and onboarding upload buttons accept .tex alongside .pdf."""
    response = app_client.post(
        "/api/settings/resume",
        files={"file": ("resume.tex", SOURCE.encode("utf-8"), "text/x-tex")},
    )
    assert response.status_code == 200
    assert response.json()["tex"]["present"] is True
    assert (resume_tmp / "resume.tex").read_text() == SOURCE


def test_an_unsupported_extension_still_names_the_formats_that_work(app_client, resume_tmp):
    response = app_client.post(
        "/api/settings/resume", files={"file": ("resume.docx", b"not a resume", "application/octet-stream")}
    )
    assert response.status_code == 400
    assert ".tex" in response.json()["detail"]


# ------------------------------------------------------------- engine settings

def test_the_engine_status_says_when_nothing_is_installed(app_client, monkeypatch):
    monkeypatch.setattr(latex, "latex_bin", lambda: "")
    body = app_client.get("/api/settings/latex").json()
    assert body["available"] is False
    assert "tectonic" in body["candidates"]


def test_a_path_that_cannot_be_run_is_refused(app_client, monkeypatch):
    monkeypatch.setattr(latex, "latex_version", lambda _path=None: None)
    response = app_client.post("/api/settings/latex-path", json={"path": "/nope/tectonic"})
    assert response.status_code == 400
    assert "tectonic" in response.json()["detail"]


def test_a_working_path_is_saved(app_client, monkeypatch):
    import database

    monkeypatch.setattr(latex, "latex_version", lambda _path=None: "Tectonic 0.15.0")
    app_client.post("/api/settings/latex-path", json={"path": "/opt/homebrew/bin/tectonic"})
    assert database.get_setting("latex_bin") == "/opt/homebrew/bin/tectonic"


def test_an_empty_path_clears_the_override(app_client, monkeypatch):
    """How a user undoes a wrong guess without editing the database."""
    import database

    database.set_setting("latex_bin", "/wrong/place")
    monkeypatch.setattr(latex, "latex_bin", lambda: "")
    app_client.post("/api/settings/latex-path", json={"path": ""})
    assert database.get_setting("latex_bin") == ""


# ------------------------------------------ not clobbering the user's own files

def test_an_uploaded_resume_is_never_overwritten_by_a_render(
    app_client, resume_tmp, compiles
):
    """The whole hazard this guards against: open the editor, type, and find the
    PDF you uploaded replaced by a rendered template."""
    uploaded = resume_tmp / "resume.pdf"
    uploaded.write_bytes(b"%PDF-1.4 the user's own file")

    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    app_client.post(f"/api/resumes/{instance['id']}/default")
    app_client.post(f"/api/resumes/{instance['id']}/compile")

    assert uploaded.read_bytes() == b"%PDF-1.4 the user's own file"
    assert (resume_tmp / "resume-active.pdf").read_bytes() == FAKE_PDF


def test_the_first_version_takes_over_scoring_only_when_nothing_else_is(
    app_client, resume_tmp, no_engine
):
    """With a resume already loaded, creating a version must not silently
    change what listings are scored against."""
    app_client.post(
        "/api/settings/resume", files={"file": ("resume.txt", b"x" * 400, "text/plain")}
    )
    assert app_client.post("/api/resumes", json={"name": "Base"}).json()["is_default"] is False


def test_the_first_version_does_take_over_when_no_resume_is_loaded(app_client, resume_tmp):
    assert app_client.post("/api/resumes", json={"name": "Base"}).json()["is_default"] is True


def test_switching_formats_clears_the_render_it_replaces(app_client, resume_tmp, monkeypatch):
    """A stale resume-active.txt left beside a newer .pdf would be a second
    answer to "what is being scored"."""
    import resume_loader

    monkeypatch.setattr(resume_loader, "render_tex_to_text", lambda source: (None, "stripped text"))
    app_client.put("/api/settings/resume-tex", json={"latex": SOURCE})
    assert (resume_tmp / "resume-active.txt").is_file()

    monkeypatch.setattr(resume_loader, "render_tex_to_text", lambda source: (FAKE_PDF, "rendered"))
    app_client.put("/api/settings/resume-tex", json={"latex": SOURCE})
    assert (resume_tmp / "resume-active.pdf").is_file()
    assert not (resume_tmp / "resume-active.txt").exists()


# ---------------------------------------------------------------------- assets

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def upload_asset(client, name, content=PNG):
    return client.post("/api/resumes/assets", files={"file": (name, content, "image/png")})


def test_there_are_no_assets_to_start(app_client, resume_tmp):
    assert app_client.get("/api/resumes/assets").json() == []


def test_an_image_can_be_uploaded_and_listed(app_client, resume_tmp):
    assert upload_asset(app_client, "seal.png").status_code == 201
    listed = app_client.get("/api/resumes/assets").json()
    assert [row["name"] for row in listed] == ["seal.png"]
    assert listed[0]["size"] == len(PNG)


def test_the_assets_route_is_not_mistaken_for_a_resume_id(app_client, resume_tmp):
    """`/api/resumes/assets` and `/api/resumes/{id}` share a prefix; the
    int-typed route would answer 422 if it were matched first."""
    assert app_client.get("/api/resumes/assets").status_code == 200


def test_an_asset_can_be_deleted(app_client, resume_tmp):
    upload_asset(app_client, "seal.png")
    assert app_client.delete("/api/resumes/assets/seal.png").status_code == 204
    assert app_client.get("/api/resumes/assets").json() == []


def test_deleting_one_that_is_not_there_is_a_404(app_client, resume_tmp):
    assert app_client.delete("/api/resumes/assets/ghost.png").status_code == 404


def test_re_uploading_replaces_rather_than_duplicating(app_client, resume_tmp):
    upload_asset(app_client, "seal.png", b"first")
    upload_asset(app_client, "seal.png", PNG)
    listed = app_client.get("/api/resumes/assets").json()
    assert len(listed) == 1
    assert listed[0]["size"] == len(PNG)


def test_an_unsupported_type_is_refused_and_says_what_works(app_client, resume_tmp):
    response = app_client.post(
        "/api/resumes/assets", files={"file": ("payload.sh", b"#!/bin/sh\\nrm -rf /", "text/plain")}
    )
    assert response.status_code == 400
    assert ".png" in response.json()["detail"]


def test_an_empty_upload_is_refused(app_client, resume_tmp):
    assert app_client.post(
        "/api/resumes/assets", files={"file": ("seal.png", b"", "image/png")}
    ).status_code == 400


# ------------------------------------------------------- assets: path traversal

@pytest.mark.parametrize(
    "hostile",
    [
        "../../../../etc/passwd.png",
        "..\\\\..\\\\Windows\\\\system.png",
        "/etc/cron.d/evil.png",
        "....//....//escape.png",
    ],
)
def test_a_traversing_name_lands_in_the_assets_directory_anyway(app_client, resume_tmp, hostile):
    """Uploads are named by the client, so the name is hostile input. Whatever
    it looks like, the file has to end up inside the assets directory."""
    response = upload_asset(app_client, hostile)
    assert response.status_code == 201
    saved = resume_tmp / "data" / "resume-assets" / response.json()["name"]
    assert saved.is_file()
    assert saved.resolve().parent == (resume_tmp / "data" / "resume-assets").resolve()


def test_a_traversing_delete_cannot_reach_outside(app_client, resume_tmp):
    """The router normalises this away before the handler ever sees it, which
    is a fine outcome — what matters is that the file is still there."""
    victim = resume_tmp / "resume.tex"
    victim.write_text("do not delete me")
    response = app_client.delete("/api/resumes/assets/..%2F..%2Fresume.tex")
    assert response.status_code in (400, 404, 405)
    assert victim.is_file()
    assert victim.read_text() == "do not delete me"


@pytest.mark.parametrize(
    "hostile",
    ["../resume.tex", "../../etc/passwd", "/etc/passwd", "..", ".", "", "seal.png/../../x.png"],
)
def test_the_resolver_refuses_anything_outside_the_assets_directory(resume_tmp, hostile):
    """Tested directly rather than only through HTTP: the router happens to
    normalise most of these away today, which would hide a broken resolver."""
    with pytest.raises((resumes.AssetError, resumes.ResumeNotFound)):
        resumes.delete_asset(hostile)


def test_the_resolver_accepts_a_plain_name(resume_tmp):
    resumes.save_asset("seal.png", PNG)
    assert resumes._asset_path("seal.png").parent == resumes.ASSETS_DIR.resolve()


def test_a_dotfile_name_is_not_saved_as_a_hidden_file(app_client, resume_tmp):
    response = upload_asset(app_client, ".hidden.png")
    assert not response.json()["name"].startswith(".")


def test_a_very_long_name_keeps_its_extension(app_client, resume_tmp):
    """Truncating the whole name would drop the suffix that was just checked."""
    response = upload_asset(app_client, "a" * 400 + ".png")
    name = response.json()["name"]
    assert name.endswith(".png")
    assert len(name) <= resumes.MAX_NAME_LENGTH


# --------------------------------------------------------- assets at compile time

def test_assets_are_staged_beside_the_source_when_compiling(app_client, resume_tmp, monkeypatch):
    """The compile runs in an empty temp directory, so \\includegraphics can
    only resolve a file that was copied in next to the document."""
    seen: dict[str, object] = {}

    def _capture(source, **kwargs):
        staged = kwargs.get("assets") or []
        seen["names"] = sorted(path.name for path in staged)
        return latex.CompileResult(ok=True, pdf_bytes=FAKE_PDF, log="", engine="tectonic")

    monkeypatch.setattr(resumes.latex, "compile_pdf", _capture)
    upload_asset(app_client, "seal.png")
    upload_asset(app_client, "headshot.jpg")

    instance = app_client.post("/api/resumes", json={"name": "Base"}).json()
    app_client.post(f"/api/resumes/{instance['id']}/compile")

    assert seen["names"] == ["headshot.jpg", "seal.png"]


# ------------------------------------------------- pdflatex-only compatibility

ATS_TEMPLATE = r"""\documentclass[letterpaper,11pt]{article}
\usepackage{fontawesome5}
\input{glyphtounicode}
\begin{document}
Aiden King
\end{document}
\pdfgentounicode=1
"""


def test_a_version_reports_the_constructs_that_will_not_compile(app_client, resume_tmp):
    instance = app_client.post(
        "/api/resumes", json={"name": "ATS", "latex": ATS_TEMPLATE}
    ).json()
    assert [issue["id"] for issue in instance["issues"]] == [
        "glyphtounicode-input",
        "pdfgentounicode",
    ]
    assert instance["issues"][0]["line"] == 3


def test_fixing_a_version_rewrites_its_source_in_place(app_client, resume_tmp):
    """Not a compile-time rewrite: the editor has to show the document that
    will actually be rendered."""
    instance = app_client.post(
        "/api/resumes", json={"name": "ATS", "latex": ATS_TEMPLATE}
    ).json()
    fixed = app_client.post(f"/api/resumes/{instance['id']}/fix").json()

    assert fixed["issues"] == []
    assert r"\ifdefined\pdfgentounicode\input{glyphtounicode}\fi" in fixed["latex"]
    # And it is genuinely saved, not just reported back.
    assert app_client.get(f"/api/resumes/{instance['id']}").json()["issues"] == []


def test_fixing_leaves_the_rest_of_the_document_alone(app_client, resume_tmp):
    instance = app_client.post(
        "/api/resumes", json={"name": "ATS", "latex": ATS_TEMPLATE}
    ).json()
    fixed = app_client.post(f"/api/resumes/{instance['id']}/fix").json()["latex"]
    assert r"\usepackage{fontawesome5}" in fixed
    assert "Aiden King" in fixed
    assert len(fixed.splitlines()) == len(ATS_TEMPLATE.splitlines())


def test_fixing_a_clean_version_changes_nothing(app_client, resume_tmp):
    instance = app_client.post(
        "/api/resumes", json={"name": "Clean", "latex": "\\documentclass{article}"}
    ).json()
    before = instance["updated_at"]
    fixed = app_client.post(f"/api/resumes/{instance['id']}/fix").json()
    assert fixed["latex"] == "\\documentclass{article}"
    assert fixed["updated_at"] == before


def test_fixing_an_unknown_version_is_a_404(app_client, resume_tmp):
    assert app_client.post("/api/resumes/404/fix").status_code == 404


def test_the_list_view_omits_issues_rather_than_reporting_none(app_client, resume_tmp):
    """It has no `latex` to derive them from. The key is absent, not an empty
    list, because an empty list would read as "this one is fine"."""
    app_client.post("/api/resumes", json={"name": "ATS", "latex": ATS_TEMPLATE})
    assert "issues" not in app_client.get("/api/resumes").json()[0]


# ------------------------------------------------- the same check at import

def test_an_uploaded_tex_reports_its_issues_immediately(app_client, resume_tmp, no_engine):
    """The point of checking at import: the fix is offered before the user
    meets a red compile error."""
    app_client.post(
        "/api/settings/resume",
        files={"file": ("resume.tex", ATS_TEMPLATE.encode(), "text/x-tex")},
    )
    body = app_client.get("/api/settings/resume-tex").json()
    assert [issue["id"] for issue in body["issues"]] == [
        "glyphtounicode-input",
        "pdfgentounicode",
    ]


def test_fixing_the_uploaded_tex_writes_it_back(app_client, resume_tmp, no_engine):
    app_client.put("/api/settings/resume-tex", json={"latex": ATS_TEMPLATE})
    status = app_client.post("/api/settings/resume-tex/fix").json()

    assert status["tex"]["issues"] == []
    assert r"\ifdefined\pdfgentounicode" in (resume_tmp / "resume.tex").read_text()


def test_a_new_version_started_from_a_fixed_tex_is_clean(app_client, resume_tmp, no_engine):
    app_client.put("/api/settings/resume-tex", json={"latex": ATS_TEMPLATE})
    app_client.post("/api/settings/resume-tex/fix")
    assert app_client.post("/api/resumes", json={"name": "From source"}).json()["issues"] == []


def test_fixing_with_nothing_uploaded_says_so(app_client, resume_tmp):
    response = app_client.post("/api/settings/resume-tex/fix")
    assert response.status_code == 400
    assert "uploaded" in response.json()["detail"]
