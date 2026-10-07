"""Unit coverage for the pure keyword matcher."""

from __future__ import annotations

import ast
from pathlib import Path

import keywords
from keywords import coverage, fold, plain_text, tokenize

# A whitelist rather than a blacklist. Any new import into the pure half should
# cost someone a deliberate edit here, which is the only thing that keeps it
# pure as the module grows.
ALLOWED_IMPORTS = {"__future__", "re", "typing", "latex"}

# The shape resume.tex uses for every project. latex.strip_latex only unwraps
# the flat \href{url}{label} form, so this nested one leaks its url.
NESTED_HREF_HEADING = (
    r"\resumeProjectHeading{\href{https://github.com/me/pytorch-oracle}"
    r"{\textbf{Delphi} $|$ \emph{Rust, LLVM}}}{Jan 2024}"
)


def _term(term: str, **extra) -> dict:
    return {"term": term, "bucket": "technical", "weight": 1.0, "variants": [], **extra}


def test_a_url_in_a_nested_href_does_not_make_its_path_segments_count_as_covered():
    report = coverage([_term("PyTorch")], [("p1", NESTED_HREF_HEADING)])

    assert report[0]["covered"] is False
    assert report[0]["hits"] == 0
    assert report[0]["where"] == []


def test_the_label_beside_a_stripped_url_is_still_matchable():
    report = coverage([_term("Delphi"), _term("Rust")], [("p1", NESTED_HREF_HEADING)])

    assert [row["covered"] for row in report] == [True, True]


def test_the_four_forms_of_optimize_all_match_each_other():
    assert len({fold("optimize"), fold("optimized"), fold("optimizes"), fold("optimizing")}) == 1

    report = coverage(
        [_term("optimize")],
        [("a", "Optimized the solver"), ("b", "optimizing throughput"), ("c", "optimizes caches")],
    )
    assert report[0]["hits"] == 3
    assert report[0]["where"] == ["a", "b", "c"]


def test_led_is_not_folded_away_to_a_single_letter():
    assert fold("led") == "led"

    report = coverage([_term("led")], [("a", "Led a team of four")])
    assert report[0]["covered"] is True


def test_c_plus_plus_and_c_sharp_survive_tokenization_as_whole_terms():
    assert tokenize("C++ and C# and C") == ["c++", "and", "c#", "and", "c"]

    report = coverage([_term("C++"), _term("C#")], [("a", "Shipped a C++ kernel")])
    assert [row["covered"] for row in report] == [True, False]


def test_a_multi_word_term_matches_only_when_the_words_are_contiguous_and_in_order():
    report = coverage([_term("machine learning")], [("a", "Built machine learning pipelines")])

    assert report[0]["covered"] is True
    assert report[0]["hits"] == 1


def test_a_multi_word_term_does_not_match_when_the_same_words_appear_scattered():
    scattered = "Ran the machine in the lab while learning Verilog"
    report = coverage([_term("machine learning")], [("a", scattered)])

    assert report[0]["covered"] is False
    assert report[0]["hits"] == 0

    reversed_order = coverage([_term("machine learning")], [("a", "learning machine")])
    assert reversed_order[0]["covered"] is False


def test_matching_is_case_insensitive_on_both_sides():
    report = coverage([_term("KUBERNETES")], [("a", "deployed kubernetes clusters")])

    assert report[0]["covered"] is True
    assert report[0]["term"] == "KUBERNETES"


def test_a_variant_hit_is_reported_against_the_parent_term():
    report = coverage(
        [_term("analysis", variants=["analyses", "analytic"])],
        [("a", "Produced weekly analyses of the run")],
    )

    assert report[0]["term"] == "analysis"
    assert report[0]["covered"] is True
    assert report[0]["hits"] == 1


def test_a_variant_that_folds_onto_the_term_does_not_double_count_one_mention():
    report = coverage(
        [_term("optimize", variants=["optimized", "optimizing"])],
        [("a", "Optimized the solver")],
    )

    assert report[0]["hits"] == 1


def test_where_lists_every_segment_a_term_appears_in_and_hits_counts_occurrences():
    report = coverage(
        [_term("Python")],
        [("a", "Python here and Python again"), ("b", "no mention"), ("c", "Python once")],
    )

    assert report[0]["hits"] == 3
    assert report[0]["where"] == ["a", "c"]


def test_an_empty_keyword_list_returns_an_empty_report_rather_than_raising():
    assert coverage([], [("a", "some text")]) == []


def test_a_keyword_with_no_usable_tokens_is_reported_uncovered_rather_than_matching_everything():
    report = coverage([_term("---")], [("a", "any text at all")])

    assert report[0]["covered"] is False
    assert report[0]["hits"] == 0


def test_output_order_follows_input_keyword_order():
    terms = ["Rust", "Python", "Verilog", "Qiskit"]
    report = coverage([_term(term) for term in terms], [("a", "Qiskit and Python")])

    assert [row["term"] for row in report] == terms


def test_plain_text_drops_the_url_and_keeps_the_prose_around_it():
    out = plain_text(NESTED_HREF_HEADING)

    assert "pytorch" not in out.lower()
    assert "github" not in out.lower()
    assert "Delphi" in out


def test_the_matcher_imports_nothing_that_needs_a_model_a_socket_or_a_database():
    """Purity is the feature, not a tidiness preference.

    The coverage panel re-runs this on every edit of a draft, and a matcher
    that reached for `claude_cli` or a connection could be neither fast enough
    nor testable without stubbing half the app.
    """
    tree = ast.parse(Path(keywords.__file__).read_text(encoding="utf-8"))

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported <= ALLOWED_IMPORTS, f"unexpected imports: {sorted(imported - ALLOWED_IMPORTS)}"
