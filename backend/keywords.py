"""Keyword coverage: which of a job ad's own terms a resume draft actually uses.

Pure by design. No database, no network, no `claude_cli` import. The coverage
panel re-runs this on every edit, and a matcher that needs a model or a socket
could neither be fast enough nor tested without one.

Both sides reduce to the same normal form, a list of folded tokens, and a
keyword matches when its tokens appear as a contiguous run of a segment's
tokens. A single-word term is the one-token case of that same rule, so there is
no second code path for it.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

from latex import strip_latex

_SUFFIXES_LONGEST_FIRST = ("ing", "ed", "es", "s")

# Enough of a stem to survive suffix stripping. "led" keeps its "ed" because
# "l" is not a word.
_MIN_STEM = 4

_TOKEN_RE = re.compile(r"[A-Za-z0-9+#]+")

_URL_RE = re.compile(r"\b(?:https?://|www\.)[^\s{}\[\]()\\]+", re.IGNORECASE)


def fold(token: str) -> str:
    """One token to its comparison form.

    Applied identically to both sides, so consistency matters more than
    linguistic correctness. Unifies optimize / optimized / optimizes /
    optimizing on `optimiz`, which is the case the ad-mimicking advice needs.
    Irregular morphology (analysis / analyses) belongs in a keyword's
    `variants`, not here.
    """
    folded = token.lower()
    for suffix in _SUFFIXES_LONGEST_FIRST:
        if folded.endswith(suffix) and len(folded) - len(suffix) >= _MIN_STEM:
            folded = folded[: -len(suffix)]
            break
    if folded.endswith("e") and len(folded) - 1 >= _MIN_STEM:
        folded = folded[:-1]
    return folded


def tokenize(text: str) -> list[str]:
    """Plain text to folded tokens.

    A token is a maximal run of [a-z0-9+#], so `C++` and `C#` survive as single
    tokens rather than collapsing to `c`.
    """
    return [fold(match.group()) for match in _TOKEN_RE.finditer(text)]


def plain_text(latex_or_text: str) -> str:
    """Readable text from a draft segment, LaTeX or not.

    Order is load-bearing. `latex.strip_latex` only unwraps the two-argument
    `\\href{url}{label}` form; on the nested
    `\\href{url}{\\textbf{..}}` form that `resume.tex` uses for every project
    heading it leaks the url into the output, so a repo url containing
    "pytorch" would mark the keyword PyTorch covered. Stripping urls first
    removes that whole class of false positive.
    """
    return strip_latex(_URL_RE.sub(" ", latex_or_text))


def _needles(term: str, variants: Any) -> list[tuple[str, ...]]:
    """Every folded token sequence that counts as a hit on `term`.

    Deduped: a variant that folds onto the term would otherwise count the same
    position twice.
    """
    forms: list[Any] = [term]
    if isinstance(variants, (list, tuple)):
        forms.extend(variants)
    seen: set[tuple[str, ...]] = set()
    needles: list[tuple[str, ...]] = []
    for form in forms:
        tokens = tuple(tokenize(str(form)))
        if tokens and tokens not in seen:
            seen.add(tokens)
            needles.append(tokens)
    return needles


def _occurrences(haystack: Sequence[str], needle: tuple[str, ...]) -> int:
    width = len(needle)
    return sum(
        1
        for start in range(len(haystack) - width + 1)
        if tuple(haystack[start : start + width]) == needle
    )


def coverage(keywords: Iterable[dict], segments: Iterable[tuple[str, str]]) -> list[dict]:
    """Which keywords the draft already uses, and where.

    `keywords` are `{term, bucket, weight, variants}` rows; `segments` are
    `(segment_ref, text)` pairs. Returns one row per keyword in the order the
    keywords were given.

    Each segment is normalised through `plain_text` here rather than at the
    call site. Getting that order wrong is silent, and it only has to happen
    once anywhere to make the whole report lie.
    """
    haystacks = [(ref, tuple(tokenize(plain_text(text)))) for ref, text in segments]

    report = []
    for keyword in keywords:
        term = str(keyword.get("term") or "").strip()
        needles = _needles(term, keyword.get("variants"))
        hits = 0
        where: list[str] = []
        for ref, tokens in haystacks:
            found = sum(_occurrences(tokens, needle) for needle in needles)
            if found:
                hits += found
                if ref not in where:
                    where.append(ref)
        report.append(
            {
                "term": term,
                "bucket": str(keyword.get("bucket") or "technical"),
                "covered": hits > 0,
                "hits": hits,
                "where": where,
            }
        )
    return report
