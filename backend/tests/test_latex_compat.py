r"""Detecting and repairing pdflatex-only constructs.

The document these were written against is the "Jake Gutierrez" resume, far
and away the most copied LaTeX resume template, which fails under XeTeX on two
lines and works on every other one.
"""

from __future__ import annotations

import latex_compat

TEMPLATE = r"""\documentclass[letterpaper,11pt]{article}
\usepackage{fontawesome5}
\input{glyphtounicode}

\begin{document}
Aiden King
\end{document}

% Ensure that generated pdf is machine readable/ATS parsable
\pdfgentounicode=1
"""


def test_it_finds_both_pdflatex_only_lines():
    found = latex_compat.check(TEMPLATE)
    assert [issue["id"] for issue in found] == ["glyphtounicode-input", "pdfgentounicode"]
    assert [issue["line"] for issue in found] == [3, 10]


def test_each_finding_explains_itself():
    issue = latex_compat.check(TEMPLATE)[0]
    assert "XeTeX" in issue["detail"]
    assert issue["snippet"] == r"\input{glyphtounicode}"


def test_a_clean_document_has_nothing_to_report():
    assert latex_compat.check(r"\documentclass{article}\begin{document}hi\end{document}") == []


def test_no_source_at_all_is_not_an_error():
    assert latex_compat.check(None) == []
    assert latex_compat.check("") == []


# --------------------------------------------------------------------- fixing

def test_fixing_guards_both_lines():
    fixed, applied = latex_compat.apply_fixes(TEMPLATE)
    assert set(applied) == {"glyphtounicode-input", "pdfgentounicode"}
    assert r"\ifdefined\pdfgentounicode\input{glyphtounicode}\fi" in fixed
    assert r"\ifdefined\pdfgentounicode\pdfgentounicode=1\fi" in fixed


def test_a_fixed_document_reports_nothing_further():
    fixed, _ = latex_compat.apply_fixes(TEMPLATE)
    assert latex_compat.check(fixed) == []


def test_fixing_twice_does_not_nest_the_guard():
    """The editor can ask again at any time; the second pass must be a no-op."""
    once, _ = latex_compat.apply_fixes(TEMPLATE)
    twice, applied = latex_compat.apply_fixes(once)
    assert twice == once
    assert applied == []


def test_everything_else_in_the_document_is_left_alone():
    fixed, _ = latex_compat.apply_fixes(TEMPLATE)
    for untouched in (
        r"\documentclass[letterpaper,11pt]{article}",
        r"\usepackage{fontawesome5}",
        "Aiden King",
        "% Ensure that generated pdf is machine readable/ATS parsable",
    ):
        assert untouched in fixed


def test_the_line_count_is_unchanged_so_reported_lines_still_mean_something():
    fixed, _ = latex_compat.apply_fixes(TEMPLATE)
    assert len(fixed.splitlines()) == len(TEMPLATE.splitlines())


def test_a_document_with_no_trailing_newline_keeps_not_having_one():
    source = r"\pdfgentounicode=1"
    fixed, _ = latex_compat.apply_fixes(source)
    assert fixed == r"\ifdefined\pdfgentounicode\pdfgentounicode=1\fi"


def test_line_endings_survive():
    fixed, _ = latex_compat.apply_fixes("\\pdfgentounicode=1\r\nafter\r\n")
    assert fixed.endswith("\r\nafter\r\n")
    assert "\\fi\r\n" in fixed


def test_only_the_requested_rule_is_applied():
    """The UI offers them together today, but a user fixing one at a time
    should not silently get the other."""
    fixed, applied = latex_compat.apply_fixes(TEMPLATE, ids=["pdfgentounicode"])
    assert applied == ["pdfgentounicode"]
    assert r"\ifdefined\pdfgentounicode\pdfgentounicode=1\fi" in fixed
    assert "\n\\input{glyphtounicode}\n" in fixed


def test_spacing_variants_are_recognised():
    for variant in (
        r"\input{glyphtounicode}",
        r"\input {glyphtounicode}",
        r"\input{ glyphtounicode }",
        r"\pdfgentounicode=1",
        r"\pdfgentounicode = 1",
    ):
        assert latex_compat.check(variant), variant


def test_a_similarly_named_command_is_not_touched():
    """`\\pdfgentounicodeplus` is not a thing, but a prefix match would also
    catch a user's own `\\pdfgentounicodefallback` macro."""
    source = r"\newcommand{\pdfgentounicodefallback}{x}"
    assert latex_compat.check(source) == []


def test_the_guard_leaves_the_document_working_under_pdflatex():
    """`\\ifdefined` is true there, so the guarded body still runs. Encoded as
    a test because the whole reason for guarding rather than deleting is that
    the same file has to keep working where it came from."""
    fixed, _ = latex_compat.apply_fixes(TEMPLATE)
    for line in fixed.splitlines():
        if latex_compat.GUARD in line:
            assert line.endswith(r"\fi")
            assert line.count(latex_compat.GUARD) == 1
