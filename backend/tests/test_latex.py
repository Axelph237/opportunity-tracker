"""Log parsing and the no-engine text fallback.

Actually invoking a TeX engine is out of scope here — the conftest forbids it,
because whether a compile succeeds would otherwise depend on what happens to be
installed on the machine running the suite.
"""

from __future__ import annotations

import latex


# ------------------------------------------------------------------ log parsing

def test_parses_the_classic_bang_form_with_its_line_number():
    log = """
! Undefined control sequence.
l.42 \\textbfx
                {broken}
"""
    errors = latex.parse_log(log)
    assert errors == [{"line": 42, "message": "Undefined control sequence."}]


def test_parses_the_file_line_form_tectonic_emits():
    log = "./resume.tex:17: LaTeX Error: File `fontawesome.sty' not found."
    assert latex.parse_log(log) == [
        {"line": 17, "message": "LaTeX Error: File `fontawesome.sty' not found."}
    ]


def test_keeps_a_diagnostic_that_carries_no_line_number():
    errors = latex.parse_log("error: the package could not be fetched")
    assert errors == [{"line": None, "message": "the package could not be fetched"}]


def test_drops_the_generic_tectonic_trailer():
    """`halted on potentially-recoverable error` says nothing the real error did
    not already say, and showing it first buries the useful message."""
    log = """
./resume.tex:3: Missing $ inserted.
error: halted on potentially-recoverable error
"""
    assert [e["message"] for e in latex.parse_log(log)] == ["Missing $ inserted."]


def test_deduplicates_a_message_repeated_across_two_passes():
    log = "./resume.tex:5: Undefined control sequence.\n" * 3
    assert len(latex.parse_log(log)) == 1


def test_caps_the_number_of_errors_returned():
    log = "\n".join(f"./resume.tex:{n}: Error number {n}." for n in range(1, 200))
    assert len(latex.parse_log(log)) == 50


def test_a_clean_log_yields_nothing():
    assert latex.parse_log("Output written on resume.pdf (1 page, 40000 bytes).") == []


# -------------------------------------------------------------- strip_latex

SAMPLE = r"""
\documentclass{article}
\usepackage{geometry}
\begin{document}
\section{Experience}
% a comment that should not survive
\textbf{Quantum Labs} \hfill Chicago, IL
\begin{itemize}
  \item Built a \textit{simulator} in C++ handling 30\% more qubits.
  \item See \href{https://example.com}{the write-up}.
\end{itemize}
\end{document}
"""


def test_strip_latex_keeps_the_prose():
    text = latex.strip_latex(SAMPLE)
    assert "Quantum Labs" in text
    assert "Built a simulator in C++" in text
    assert "30% more qubits" in text


def test_strip_latex_keeps_the_link_label_not_the_url():
    text = latex.strip_latex(SAMPLE)
    assert "the write-up" in text
    assert "example.com" not in text


def test_strip_latex_discards_markup_and_the_preamble():
    text = latex.strip_latex(SAMPLE)
    for noise in ("\\documentclass", "\\usepackage", "geometry", "itemize", "{", "}", "%  a comment"):
        assert noise not in text
    assert "a comment that should not survive" not in text


def test_strip_latex_on_source_with_no_document_environment():
    """A fragment the user pasted in is still worth reading as text."""
    assert latex.strip_latex(r"\textbf{Jane Doe} --- physicist") == "Jane Doe --- physicist"


def test_strip_latex_collapses_runs_of_blank_lines():
    assert "\n\n\n" not in latex.strip_latex("a\n\n\n\n\nb")


# ------------------------------------------------------------- engine discovery

def test_engine_status_reports_unavailable_when_nothing_is_installed(monkeypatch, db_path):
    monkeypatch.setattr(latex, "latex_bin", lambda: "")
    status = latex.engine_status()
    assert status["available"] is False
    assert status["path"] is None
    assert "tectonic" in status["candidates"]


def test_a_saved_setting_beats_whatever_is_on_path(monkeypatch, db_path):
    monkeypatch.setattr(latex.shutil, "which", lambda _name: "/usr/bin/pdflatex")
    import database

    database.set_setting("latex_bin", "/opt/homebrew/bin/tectonic")
    assert latex.latex_bin() == "/opt/homebrew/bin/tectonic"


def test_falls_back_to_the_first_known_engine_on_path(monkeypatch, db_path):
    monkeypatch.setattr(
        latex.shutil, "which", lambda name: "/usr/bin/xelatex" if name == "xelatex" else None
    )
    assert latex.latex_bin() == "/usr/bin/xelatex"


# ----------------------------------------------------- the vendored engine

def test_the_vendored_engine_is_used_when_the_machine_has_none(
    monkeypatch, tmp_path, db_path
):
    """scripts/install.sh drops Tectonic in vendor/bin when nothing was on
    PATH, and nothing puts that directory on PATH afterwards."""
    vendor = tmp_path / "vendor" / "bin"
    vendor.mkdir(parents=True)
    binary = vendor / "tectonic"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)

    monkeypatch.setattr(latex, "VENDOR_DIR", vendor)
    monkeypatch.setattr(latex.shutil, "which", lambda _name: None)

    assert latex.latex_bin() == str(binary)


def test_an_engine_on_path_beats_the_vendored_one(monkeypatch, tmp_path, db_path):
    """A TeX distribution the user manages should win over the copy we
    downloaded as a fallback."""
    vendor = tmp_path / "vendor" / "bin"
    vendor.mkdir(parents=True)
    binary = vendor / "tectonic"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)

    monkeypatch.setattr(latex, "VENDOR_DIR", vendor)
    monkeypatch.setattr(
        latex.shutil, "which", lambda name: "/usr/local/bin/tectonic" if name == "tectonic" else None
    )

    assert latex.latex_bin() == "/usr/local/bin/tectonic"


def test_a_vendored_file_that_is_not_executable_is_ignored(monkeypatch, tmp_path, db_path):
    """A half-written download should read as "no engine", not as a broken one."""
    vendor = tmp_path / "vendor" / "bin"
    vendor.mkdir(parents=True)
    (vendor / "tectonic").write_text("partial download")
    (vendor / "tectonic").chmod(0o644)

    monkeypatch.setattr(latex, "VENDOR_DIR", vendor)
    monkeypatch.setattr(latex.shutil, "which", lambda _name: None)

    assert latex.latex_bin() == ""


def test_a_saved_setting_still_beats_the_vendored_engine(monkeypatch, tmp_path, db_path):
    import database

    vendor = tmp_path / "vendor" / "bin"
    vendor.mkdir(parents=True)
    (vendor / "tectonic").write_text("#!/bin/sh\nexit 0\n")
    (vendor / "tectonic").chmod(0o755)

    monkeypatch.setattr(latex, "VENDOR_DIR", vendor)
    monkeypatch.setattr(latex.shutil, "which", lambda _name: None)
    database.set_setting("latex_bin", "/opt/mine/xelatex")

    assert latex.latex_bin() == "/opt/mine/xelatex"


# ------------------------------------- attributing a line to the right file

# Trimmed from a real Tectonic run on a resume that used the widely-copied
# "Jake Gutierrez" template, whose \pdfglyphtounicode is pdflatex-only and
# fails under XeTeX. The error surfaces at line 7 of a support file, and
# reporting that as line 7 of the resume points the user at a blank line.
GLYPHTOUNICODE_LOG = """
(size11.clo)) (latexsym.sty) (fullpage.sty)
\\JustifyingParindent=\\skip78
) (glyphtounicode
! Undefined control sequence.
l.7 \\pdfglyphtounicode
                      {A}{0041}
No pages of output.
"""


def test_an_error_inside_a_support_file_is_not_blamed_on_the_resume():
    errors = latex.parse_log(GLYPHTOUNICODE_LOG)
    assert errors[0]["line"] is None
    assert "glyphtounicode" in errors[0]["message"]
    assert "line 7" in errors[0]["message"]


def test_an_error_in_the_document_itself_keeps_its_line():
    """The stack is back at the top level, so `l.12` is the resume's line 12."""
    log = """
(latexsym.sty) (fullpage.sty)
! Undefined control sequence.
l.12 \\nope
"""
    assert latex.parse_log(log) == [{"line": 12, "message": "Undefined control sequence."}]


def test_a_file_that_was_opened_and_closed_again_does_not_capture_the_blame():
    log = """
(glyphtounicode)
! Undefined control sequence.
l.30 \\oops
"""
    assert latex.parse_log(log) == [{"line": 30, "message": "Undefined control sequence."}]


def test_tectonics_extensionless_location_names_the_file():
    errors = latex.parse_log("error: glyphtounicode:7: Undefined control sequence")
    assert errors == [
        {"line": None, "message": "Undefined control sequence (in glyphtounicode, line 7)"}
    ]


def test_a_located_error_in_the_resume_itself_still_carries_its_line():
    assert latex.parse_log("./resume.tex:42: Missing $ inserted.") == [
        {"line": 42, "message": "Missing $ inserted."}
    ]


def test_the_jobname_is_what_decides_whose_lines_these_are():
    """compile_pdf names the temp file after the job, so the parser has to be
    told what that name is rather than assuming "resume"."""
    log = "(r.tex\n! Undefined control sequence.\nl.9 \\x\n"
    assert latex.parse_log(log, jobname="r")[0]["line"] == 9
    assert latex.parse_log(log, jobname="resume")[0]["line"] is None


def test_unbalanced_brackets_in_package_chatter_do_not_desync_the_stack():
    """Package output is full of stray brackets; a push its own `)` pops again
    must leave the stack where it started."""
    log = """
Package: foo 2021/01/01 (v1.2)
[1] [2]
! Undefined control sequence.
l.5 \\bar
"""
    assert latex.parse_log(log)[0]["line"] == 5
