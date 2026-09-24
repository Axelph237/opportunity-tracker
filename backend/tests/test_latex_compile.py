"""The compile path itself, run against a stub engine.

`compile_pdf` is mostly subprocess plumbing — build an argv, run it in a
throwaway directory, find the PDF the engine left behind, read its log. None of
that is covered by unit-testing the parser, and installing a real TeX
distribution in CI to check it would be absurd. So these tests point
`latex_bin` at a shell script that behaves like an engine.

`REAL_COMPILE` is captured at import time, before conftest's autouse guard
replaces `latex.compile_pdf` with the "no test may run a real engine" stub.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

import latex

REAL_COMPILE = latex.compile_pdf


def write_engine(directory: Path, body: str, name: str = "pdflatex") -> Path:
    """Drop an executable shell script that stands in for a TeX engine."""
    script = directory / name
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


# An engine is handed `-output-directory <dir>`; these scripts find it the same
# crude way for every case, by taking the argument after that flag.
FIND_OUTDIR = '''
outdir=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-output-directory" ]; then outdir="$arg"; fi
  prev="$arg"
done
'''


@pytest.fixture
def engine_dir(tmp_path, monkeypatch):
    directory = tmp_path / "bin"
    directory.mkdir()
    return directory


def use(script: Path, monkeypatch) -> None:
    monkeypatch.setattr(latex, "latex_bin", lambda: str(script))
    monkeypatch.setattr(latex, "latex_available", lambda _path=None: True)


def test_a_successful_run_returns_the_pdf_the_engine_wrote(engine_dir, monkeypatch):
    script = write_engine(
        engine_dir,
        FIND_OUTDIR + 'printf "%%PDF-1.4 stub" > "$outdir/resume.pdf"\n'
        'echo "Output written on resume.pdf (1 page)." > "$outdir/resume.log"\n'
        "exit 0",
    )
    use(script, monkeypatch)

    result = REAL_COMPILE(r"\documentclass{article}\begin{document}hi\end{document}")

    assert result.ok is True
    assert result.pdf_bytes == b"%PDF-1.4 stub"
    assert "Output written" in result.log
    assert result.errors == []
    assert result.engine == "pdflatex"


def test_the_source_reaches_the_engine_unchanged(engine_dir, monkeypatch):
    """The document is written to a temp file and passed by path, so a stray
    quoting bug here would corrupt every render."""
    script = write_engine(
        engine_dir,
        FIND_OUTDIR + 'cp "$(eval echo \\${$#})" "$outdir/seen.tex"\n'
        'printf "%%PDF-1.4" > "$outdir/resume.pdf"\n'
        'cat "$outdir/seen.tex" > "$outdir/resume.log"\n'
        "exit 0",
    )
    use(script, monkeypatch)

    source = "\\documentclass{article}\n% a comment with 'quotes' and $math$\n"
    assert source.strip() in REAL_COMPILE(source).log


def test_a_failing_engine_raises_with_the_parsed_errors(engine_dir, monkeypatch):
    script = write_engine(
        engine_dir,
        FIND_OUTDIR + 'printf "! Undefined control sequence.\\nl.4 \\\\nope\\n" > "$outdir/resume.log"\n'
        "exit 1",
    )
    use(script, monkeypatch)

    with pytest.raises(latex.LatexCompileError) as caught:
        REAL_COMPILE(r"\nope")

    assert caught.value.errors == [{"line": 4, "message": "Undefined control sequence."}]
    assert "Undefined control sequence" in caught.value.log


def test_an_engine_that_exits_zero_without_a_pdf_is_still_a_failure(engine_dir, monkeypatch):
    """Some engines report success having produced nothing. The caller asked
    for a PDF, so no PDF is an error whatever the exit code said."""
    script = write_engine(engine_dir, FIND_OUTDIR + 'echo "nothing to do" > "$outdir/resume.log"\nexit 0')
    use(script, monkeypatch)

    with pytest.raises(latex.LatexCompileError):
        REAL_COMPILE(r"\documentclass{article}")


def test_the_engines_own_log_beats_its_stdout(engine_dir, monkeypatch):
    """`.log` carries the diagnostics; stdout is usually a banner."""
    script = write_engine(
        engine_dir,
        FIND_OUTDIR + 'echo "This is pdfTeX, Version 3.14"\n'
        'printf "%%PDF-1.4" > "$outdir/resume.pdf"\n'
        'echo "the real log" > "$outdir/resume.log"\n'
        "exit 0",
    )
    use(script, monkeypatch)

    assert REAL_COMPILE(r"\documentclass{article}").log.strip() == "the real log"


def test_a_hanging_engine_is_killed_and_reported(engine_dir, monkeypatch):
    script = write_engine(engine_dir, "sleep 30")
    use(script, monkeypatch)

    with pytest.raises(latex.LatexCompileError, match="timed out"):
        REAL_COMPILE(r"\documentclass{article}", timeout=1)


def test_nothing_is_left_behind_in_the_project(engine_dir, monkeypatch, tmp_path):
    """Auxiliary files a document writes must land in the throwaway directory,
    never next to the user's own work."""
    script = write_engine(
        engine_dir,
        FIND_OUTDIR + 'printf "%%PDF-1.4" > "$outdir/resume.pdf"\n'
        'echo aux > "$outdir/resume.aux"\n'
        "exit 0",
    )
    use(script, monkeypatch)
    before = set(os.listdir(tmp_path))

    REAL_COMPILE(r"\documentclass{article}")

    assert set(os.listdir(tmp_path)) == before


def test_a_missing_binary_is_reported_as_a_setup_problem(monkeypatch):
    monkeypatch.setattr(latex, "latex_bin", lambda: "")
    with pytest.raises(latex.LatexUnavailable, match="tectonic"):
        REAL_COMPILE(r"\documentclass{article}")


def test_an_oversized_document_is_refused_before_the_engine_runs(engine_dir, monkeypatch):
    script = write_engine(engine_dir, "exit 0")
    use(script, monkeypatch)
    with pytest.raises(latex.LatexCompileError, match="larger than"):
        REAL_COMPILE("x" * (latex.MAX_SOURCE_BYTES + 1))


# --------------------------------------------------------------- engine dialects

def test_tectonic_gets_its_own_flags(monkeypatch):
    monkeypatch.setattr(latex, "_tectonic_untrusted", lambda _binary: True)
    argv = latex._command("/opt/homebrew/bin/tectonic", Path("/tmp/r.tex"), Path("/tmp/out"))
    assert "--untrusted" in argv
    assert "--outdir" in argv
    assert "-interaction=nonstopmode" not in argv


def test_tectonic_without_untrusted_support_omits_the_flag(monkeypatch):
    """The flag only exists from 0.9 on, and passing it to an older build fails
    the whole compile rather than degrading."""
    monkeypatch.setattr(latex, "_tectonic_untrusted", lambda _binary: False)
    assert "--untrusted" not in latex._command("tectonic", Path("r.tex"), Path("out"))


def test_plain_engines_get_nonstopmode_and_no_shell_escape():
    argv = latex._command("/usr/bin/xelatex", Path("r.tex"), Path("out"))
    assert "-interaction=nonstopmode" in argv
    assert "-no-shell-escape" in argv


def test_latexmk_resolves_references_itself_so_one_pass_is_enough():
    assert latex._passes("/usr/bin/latexmk") == 1
    assert latex._passes("/opt/homebrew/bin/tectonic") == 1
    # pdflatex needs a second run for anything that references a later page.
    assert latex._passes("/usr/bin/pdflatex") == 2


def test_a_plain_engine_runs_twice_when_the_log_asks_for_it(engine_dir, monkeypatch):
    counter = engine_dir / "runs"
    script = write_engine(
        engine_dir,
        FIND_OUTDIR + f'echo x >> "{counter}"\n'
        'printf "%%PDF-1.4" > "$outdir/resume.pdf"\n'
        'echo "Rerun to get cross-references right." > "$outdir/resume.log"\n'
        "exit 0",
    )
    use(script, monkeypatch)

    REAL_COMPILE(r"\documentclass{article}")

    assert counter.read_text().count("x") == 2


def test_a_plain_engine_runs_once_when_the_log_does_not(engine_dir, monkeypatch):
    counter = engine_dir / "runs"
    script = write_engine(
        engine_dir,
        FIND_OUTDIR + f'echo x >> "{counter}"\n'
        'printf "%%PDF-1.4" > "$outdir/resume.pdf"\n'
        'echo "Output written on resume.pdf" > "$outdir/resume.log"\n'
        "exit 0",
    )
    use(script, monkeypatch)

    REAL_COMPILE(r"\documentclass{article}")

    assert counter.read_text().count("x") == 1


# ------------------------------------------------------------ version probing

REAL_VERSION = latex.latex_version


def test_a_binary_that_reports_a_version_is_accepted(engine_dir):
    script = write_engine(engine_dir, 'echo "pdfTeX 3.141592653-2.6-1.40.25"\nexit 0')
    assert REAL_VERSION(str(script)) == "pdfTeX 3.141592653-2.6-1.40.25"


def test_a_binary_that_fails_is_not_an_engine(engine_dir):
    """Otherwise any executable on the filesystem passes the path check in
    Settings, and its error message is stored as the version."""
    script = write_engine(engine_dir, 'echo "no such option --version" >&2\nexit 1')
    assert REAL_VERSION(str(script)) is None


def test_a_version_announced_on_stderr_still_counts(engine_dir):
    script = write_engine(engine_dir, 'echo "XeTeX 3.14" >&2\nexit 0')
    assert REAL_VERSION(str(script)) == "XeTeX 3.14"


def test_only_the_first_line_is_kept(engine_dir):
    script = write_engine(engine_dir, 'echo "Tectonic 0.15.0"\necho "Copyright blurb"\nexit 0')
    assert REAL_VERSION(str(script)) == "Tectonic 0.15.0"


def test_a_flood_of_output_is_truncated(engine_dir):
    script = write_engine(engine_dir, f'echo "{"v" * 1000}"\nexit 0')
    assert len(REAL_VERSION(str(script))) == 200


def test_a_path_that_does_not_exist_is_not_an_engine():
    assert REAL_VERSION("/nope/not/here/tectonic") is None
