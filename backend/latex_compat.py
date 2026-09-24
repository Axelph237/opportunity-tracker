r"""Known reasons a LaTeX resume will not compile with the engine we ship.

Tectonic runs XeTeX. The most widely copied resume templates on the internet
were written for pdflatex, and reach for primitives XeTeX simply does not have
— `\pdfgentounicode` and the `glyphtounicode` map it drives. The document is
otherwise fine: in the template this was written for, every one of its fourteen
packages loads without complaint and only two lines fail.

So rather than refuse those documents, or quietly rewrite them behind the
user's back, this module names what is wrong and offers an edit to the source
they can see. Guarding with `\ifdefined` rather than deleting matters: under
pdflatex the guarded lines still run, so applying the fix here does not break
the document anywhere else the user compiles it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterator, Optional

# What a fixed line looks like. Used to recognise already-guarded source so a
# second pass cannot nest the guard inside itself.
GUARD = r"\ifdefined\pdfgentounicode"


def _guard(match: re.Match) -> str:
    """Wrap a pdftex-only construct so engines without it skip the line."""
    return f"{GUARD}{match.group(0)}\\fi"


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    detail: str
    pattern: re.Pattern
    fix: Callable[[re.Match], str] = _guard


RULES: tuple[Rule, ...] = (
    Rule(
        id="glyphtounicode-input",
        title="pdflatex-only glyph map",
        detail=(
            "`\\input{glyphtounicode}` loads a table of pdftex glyph mappings. "
            "Tectonic runs XeTeX, which has no such table, and the compile stops "
            "on the first line of that file. Guarding it keeps the line working "
            "under pdflatex and skips it here."
        ),
        pattern=re.compile(r"\\input\s*\{\s*glyphtounicode\s*\}"),
    ),
    Rule(
        id="pdfgentounicode",
        title="pdflatex-only Unicode mapping",
        detail=(
            "`\\pdfgentounicode` is a pdftex primitive that asks for a ToUnicode "
            "map so the PDF's text can be copied and parsed. XeTeX does not "
            "define it and writes its own mapping instead."
        ),
        pattern=re.compile(r"\\pdfgentounicode\s*=\s*\d+"),
    ),
)


@dataclass(frozen=True)
class Issue:
    rule: Rule
    line: int
    snippet: str


def _scan(source: str) -> Iterator[Issue]:
    for number, text in enumerate(source.splitlines(), start=1):
        # A line already carrying the guard has been fixed; matching it again
        # would wrap the guard in another guard on every visit.
        if GUARD in text:
            continue
        for rule in RULES:
            if rule.pattern.search(text):
                yield Issue(rule=rule, line=number, snippet=text.strip()[:160])


def check(source: Optional[str]) -> list[dict]:
    """Every known incompatibility in this source, in document order."""
    if not source:
        return []
    return [
        {
            "id": issue.rule.id,
            "title": issue.rule.title,
            "detail": issue.rule.detail,
            "line": issue.line,
            "snippet": issue.snippet,
        }
        for issue in _scan(source)
    ]


def apply_fixes(source: Optional[str], ids: Optional[list[str]] = None) -> tuple[str, list[str]]:
    """Return `(fixed_source, ids_applied)`.

    Line-by-line rather than a whole-document regex so a construct inside a
    comment stays where it is relative to everything else, and so the line
    numbers reported by `check` keep meaning the same thing afterwards.
    """
    if not source:
        return source or "", []

    wanted = set(ids) if ids else None
    applied: list[str] = []
    lines = source.splitlines(keepends=True)

    for index, text in enumerate(lines):
        if GUARD in text:
            continue
        for rule in RULES:
            if wanted is not None and rule.id not in wanted:
                continue
            if not rule.pattern.search(text):
                continue
            # Split the newline off so the guard cannot swallow it.
            body = text.rstrip("\r\n")
            ending = text[len(body) :]
            lines[index] = rule.pattern.sub(rule.fix, body) + ending
            text = lines[index]
            applied.append(rule.id)

    return "".join(lines), applied
