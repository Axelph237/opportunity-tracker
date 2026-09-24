"""Compiling LaTeX to PDF through whichever TeX engine is on this machine.

The project ships no TeX distribution, so every entry point here has to cope
with there being no engine at all: `engine_status()` reports what was found and
`compile_pdf` raises `LatexUnavailable` rather than failing obscurely. The UI
uses that to show install instructions instead of a broken preview.

Engine choice mirrors `claude_cli.claude_bin()`: a saved setting wins, then the
environment, then the first known binary on PATH. Tectonic is preferred because
it is a single binary that fetches the packages it needs, which is a far smaller
ask than a full TeX Live install.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from database import PROJECT_ROOT

load_dotenv()

logger = logging.getLogger(__name__)

# In preference order. Tectonic first: no TeX Live tree, packages on demand.
KNOWN_ENGINES = ("tectonic", "latexmk", "xelatex", "pdflatex")

# Where scripts/install.sh puts the engine it downloads when the machine has
# none. Keeping it inside the project means the install needs no package
# manager and no sudo, and uninstall.sh can take it away again.
VENDOR_DIR = PROJECT_ROOT / "vendor" / "bin"

ENV_LATEX_BIN = os.getenv("LATEX_BIN", "")
DEFAULT_TIMEOUT = int(os.getenv("LATEX_TIMEOUT_SECONDS", "120"))

# A resume is one page of text. Anything past this is a runaway \loop or an
# embedded image dump, neither of which belongs in the editor.
MAX_SOURCE_BYTES = 2_000_000


class LatexUnavailable(RuntimeError):
    """Raised when no TeX engine could be found or run."""


class LatexCompileError(RuntimeError):
    """Raised when the engine ran but produced no PDF."""

    def __init__(self, message: str, log: str = "", errors: Optional[list[dict]] = None) -> None:
        super().__init__(message)
        self.log = log
        self.errors = errors or []


@dataclass
class CompileResult:
    ok: bool
    pdf_bytes: bytes = b""
    log: str = ""
    errors: list[dict] = field(default_factory=list)
    engine: str = ""
    duration_ms: int = 0


def _engine_name(path: str) -> str:
    return Path(path).name.lower()


def latex_bin() -> str:
    """Where the TeX engine lives.

    The saved setting wins, then .env, then PATH, then the copy the installer
    vendored. PATH comes first so a TeX distribution the user manages is
    preferred over ours — the vendored binary is the fallback for a machine
    that had nothing, not a replacement for what is already there.
    """
    try:
        from database import get_setting

        saved = get_setting("latex_bin")
    except Exception:
        saved = None
    if saved:
        return saved
    if ENV_LATEX_BIN:
        return ENV_LATEX_BIN
    for candidate in KNOWN_ENGINES:
        found = shutil.which(candidate)
        if found:
            return found
    vendored = VENDOR_DIR / "tectonic"
    if vendored.is_file() and os.access(vendored, os.X_OK):
        return str(vendored)
    return ""


def latex_available(path: Optional[str] = None) -> bool:
    binary = path if path is not None else latex_bin()
    if not binary:
        return False
    return shutil.which(binary) is not None or os.path.isfile(binary)


def latex_version(path: Optional[str] = None) -> Optional[str]:
    """First line of `--version`, or None when the binary is not a usable engine.

    A non-zero exit is treated as "not an engine" rather than something to
    report a version for. Without that check any executable on the filesystem
    passes `/api/settings/latex-path`, and its error message gets stored and
    displayed as though it were a version string.
    """
    binary = path if path is not None else latex_bin()
    if not binary:
        return None
    try:
        result = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    # stdout first, but some engines announce themselves on stderr.
    output = (result.stdout or result.stderr or "").strip()
    if not output:
        return None
    # A binary that floods its output should not put a paragraph in the UI.
    return output.splitlines()[0].strip()[:200]


def engine_status() -> dict[str, object]:
    binary = latex_bin()
    available = latex_available(binary)
    return {
        "available": available,
        "path": binary or None,
        "engine": _engine_name(binary) if binary else None,
        "version": latex_version(binary) if available else None,
        "candidates": list(KNOWN_ENGINES),
    }


_untrusted_support: dict[str, bool] = {}


def _tectonic_untrusted(binary: str) -> bool:
    """Whether this tectonic accepts `--untrusted`. Cached; asked once per binary.

    The flag disables shell-escape and arbitrary file reads, which is what we
    want for source the agent may have written — but it only exists from 0.9 on,
    and passing it to an older build fails the whole compile.
    """
    if binary in _untrusted_support:
        return _untrusted_support[binary]
    try:
        result = subprocess.run(
            [binary, "--help"], capture_output=True, text=True, timeout=20, check=False
        )
        supported = "--untrusted" in (result.stdout or "") + (result.stderr or "")
    except (OSError, subprocess.SubprocessError):
        supported = False
    _untrusted_support[binary] = supported
    return supported


def _command(binary: str, source: Path, outdir: Path) -> list[str]:
    """The argv for one compile pass with whichever engine this is."""
    engine = _engine_name(binary)
    if engine.startswith("tectonic"):
        args = [binary]
        if _tectonic_untrusted(binary):
            args.append("--untrusted")
        args += ["--outdir", str(outdir), "--keep-logs", "--chatter", "minimal", str(source)]
        return args
    if engine.startswith("latexmk"):
        return [
            binary, "-pdf", "-interaction=nonstopmode", "-halt-on-error",
            "-no-shell-escape", f"-outdir={outdir}", str(source),
        ]
    # pdflatex / xelatex and anything else that takes the same flags.
    return [
        binary, "-interaction=nonstopmode", "-halt-on-error", "-no-shell-escape",
        "-output-directory", str(outdir), str(source),
    ]


def _passes(binary: str) -> int:
    """latexmk and tectonic resolve references themselves; plain engines need two runs."""
    engine = _engine_name(binary)
    return 1 if engine.startswith(("tectonic", "latexmk")) else 2


# `./resume.tex:12: LaTeX Error: ...`, and tectonic's extensionless
# `glyphtounicode:7: Undefined control sequence`. The file is captured, not
# skipped, because a line number is only meaningful once you know which file
# it counts lines in.
_LOCATED_RE = re.compile(
    r"^(?:error:\s*)?(?:\./)?(?P<file>[^\s:()]+?)(?:\.tex)?:(?P<line>\d+):\s*(?P<msg>.+)$"
)
# The classic two-line form: `! Undefined control sequence.` then `l.12 \foo`
_BANG_RE = re.compile(r"^!\s*(.+)$")
_LINE_MARKER_RE = re.compile(r"^l\.(\d+)\s*(.*)$")
# Tectonic's own diagnostics, which carry no location at all.
_ERROR_RE = re.compile(r"^error:\s*(.+)$", re.IGNORECASE)

# Tectonic's trailers, matched after the `error:` prefix has been stripped.
# They restate that the compile failed without saying anything about why, and
# sorting first would bury the real message.
_NOISE = (
    "halted on potentially-recoverable error",
    "the tex engine had an unrecoverable error",
    "the tex engine failed",
)


# TeX announces every file it opens as `(name` and closes it with `)`, which is
# the only thing in a `.log` that says whose lines an `l.<n>` marker is counting.
_OPEN_FILE_RE = re.compile(r"\(([^\s()]+)")


def _track_files(stack: list[str], line: str) -> None:
    """Apply one log line's `(file` / `)` markers to the open-file stack.

    Deliberately forgiving: a stray bracket in a package's chatter pushes a
    token that its own `)` pops straight back off, so the net effect is
    nothing. Getting this slightly wrong costs a line number, not a render.
    """
    index = 0
    while index < len(line):
        char = line[index]
        if char == "(":
            match = _OPEN_FILE_RE.match(line, index)
            if match:
                stack.append(match.group(1))
                index = match.end()
                continue
            index += 1
        elif char == ")":
            if stack:
                stack.pop()
            index += 1
        else:
            index += 1


def _stem(name: str) -> str:
    return name.rsplit("/", 1)[-1].removesuffix(".tex")


def parse_log(log: str, jobname: str = "resume") -> list[dict]:
    """Pull `{line, message}` diagnostics out of an engine log.

    Line numbers are only reported when they belong to the user's own document.
    TeX counts lines per file, and a failure inside a package or a support file
    carries that file's numbering — `glyphtounicode:7` is line 7 of
    glyphtounicode.tex, not of the resume. Attributing it to the resume sends
    the editor's cursor to an unrelated line and tells the user the problem is
    somewhere it is not, which is worse than offering no line at all.

    Best effort otherwise: a message we cannot place still comes back with
    `line: None` rather than being dropped.
    """
    errors: list[dict] = []
    seen: set[tuple[Optional[int], str]] = set()

    def add(line: Optional[int], message: str) -> None:
        message = message.strip()
        if not message or message.lower().rstrip(".") in _NOISE:
            return
        key = (line, message)
        if key in seen:
            return
        seen.add(key)
        errors.append({"line": line, "message": message})

    lines = log.splitlines()
    open_files: list[str] = []

    for index, raw in enumerate(lines):
        text = raw.strip()

        match = _LOCATED_RE.match(text)
        if match:
            where = _stem(match.group("file"))
            if where == jobname:
                add(int(match.group("line")), match.group("msg"))
            else:
                # Name the file in the message: the user cannot fix a line they
                # cannot see, but knowing which package broke is actionable.
                add(None, f"{match.group('msg')} (in {where}, line {match.group('line')})")
            _track_files(open_files, raw)
            continue

        match = _BANG_RE.match(text)
        if match:
            message = match.group(1)
            # Whichever file TeX currently has open is the one `l.<n>` counts.
            # An empty stack means the top level, which is the user's document.
            current = _stem(open_files[-1]) if open_files else jobname
            number = None
            for follow in lines[index + 1 : index + 6]:
                marker = _LINE_MARKER_RE.match(follow.strip())
                if marker:
                    number = int(marker.group(1))
                    break
            if current != jobname:
                if number is not None:
                    message = f"{message} (in {current}, line {number})"
                number = None
            add(number, message)
            _track_files(open_files, raw)
            continue

        match = _ERROR_RE.match(text)
        if match:
            add(None, match.group(1))

        _track_files(open_files, raw)

    return errors[:50]


def compile_pdf(
    source: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    jobname: str = "resume",
    assets: Optional[list[Path]] = None,
) -> CompileResult:
    r"""Compile LaTeX source and return the PDF bytes.

    Everything happens in a throwaway directory, so a document that writes
    auxiliary files cannot leave anything behind in the project. `assets` are
    copied in beside the source first: a resume that does
    `\includegraphics{seal.png}` resolves the file relative to the document,
    which in an otherwise empty temp directory would always be missing.
    """
    import time

    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise LatexCompileError(
            f"Source is larger than {MAX_SOURCE_BYTES // 1_000_000} MB.", log="", errors=[]
        )

    binary = latex_bin()
    if not latex_available(binary):
        raise LatexUnavailable(
            "No LaTeX engine found. Install Tectonic (brew install tectonic) or set the path in "
            "Settings → Resume."
        )

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ot-latex-") as tmp:
        work = Path(tmp)
        tex = work / f"{jobname}.tex"
        tex.write_text(source, encoding="utf-8")
        outdir = work / "out"
        outdir.mkdir()

        for asset in assets or []:
            try:
                # By name only. A stored asset should never be able to decide
                # where in the work directory it lands.
                shutil.copyfile(asset, work / Path(asset).name)
            except OSError as exc:
                logger.warning("Could not stage asset %s: %s", asset, exc)

        log = ""
        for attempt in range(_passes(binary)):
            try:
                result = subprocess.run(
                    _command(binary, tex, outdir),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=work,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise LatexCompileError(
                    f"Compile timed out after {timeout}s. A macro may be looping.",
                    log=log,
                ) from exc
            except OSError as exc:
                raise LatexUnavailable(f"Could not run `{binary}`: {exc}") from exc

            log = f"{result.stdout or ''}\n{result.stderr or ''}".strip()
            # The engine's own .log is far more informative than its stdout.
            engine_log = outdir / f"{jobname}.log"
            if engine_log.exists():
                try:
                    log = engine_log.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass
            # A failed first pass will not improve on the second.
            if result.returncode != 0:
                break
            if attempt == 0 and _passes(binary) > 1 and "Rerun" not in log:
                break

        pdf = outdir / f"{jobname}.pdf"
        duration_ms = int((time.monotonic() - started) * 1000)
        errors = parse_log(log, jobname=jobname)

        if not pdf.exists():
            raise LatexCompileError(
                errors[0]["message"] if errors else "The engine produced no PDF.",
                log=log,
                errors=errors,
            )

        return CompileResult(
            ok=True,
            pdf_bytes=pdf.read_bytes(),
            log=log,
            # Warnings can accompany a PDF that came out fine; keep them.
            errors=errors,
            engine=_engine_name(binary),
            duration_ms=duration_ms,
        )


# ------------------------------------------------------------ text without an engine

_COMMENT_RE = re.compile(r"(?<!\\)%.*$", re.MULTILINE)
_PREAMBLE_RE = re.compile(r"^.*?\\begin\{document\}", re.DOTALL)
_END_RE = re.compile(r"\\end\{document\}.*$", re.DOTALL)
# \textbf{x} -> x, \href{url}{label} -> label
_ONE_ARG_RE = re.compile(r"\\[a-zA-Z@]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}")
_HREF_RE = re.compile(r"\\href\{[^{}]*\}\{([^{}]*)\}")
_ENV_RE = re.compile(r"\\(?:begin|end)\{[^{}]*\}(?:\[[^\]]*\])?(?:\{[^{}]*\})*")
_BARE_CMD_RE = re.compile(r"\\[a-zA-Z@]+\*?")
_BRACES_RE = re.compile(r"[{}]")
_WS_RE = re.compile(r"[ \t]+")
_BLANKS_RE = re.compile(r"\n{3,}")

_ESCAPES = {
    r"\\&": "&", r"\\%": "%", r"\\\$": "$", r"\\#": "#", r"\\_": "_",
    r"\\\{": "{", r"\\\}": "}", r"\\\\": "\n", r"~": " ",
}


def strip_latex(source: str) -> str:
    """Reduce LaTeX source to readable plain text.

    This is the fallback for scoring when no engine is installed: the classifier
    needs prose, and markup-laden source makes for a poor comparison against a
    job description. It is not a renderer and does not try to be — the compiled
    PDF is always the better input when one exists.
    """
    text = _COMMENT_RE.sub("", source)
    text = _PREAMBLE_RE.sub("", text)
    text = _END_RE.sub("", text)
    text = _HREF_RE.sub(r"\1", text)
    text = _ENV_RE.sub("\n", text)
    # Repeat: nested groups only unwrap one level per pass.
    for _ in range(4):
        replaced = _ONE_ARG_RE.sub(r"\1", text)
        if replaced == text:
            break
        text = replaced
    text = _BARE_CMD_RE.sub(" ", text)
    text = _BRACES_RE.sub("", text)
    for pattern, replacement in _ESCAPES.items():
        text = re.sub(pattern, replacement, text)
    text = _WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANKS_RE.sub("\n\n", text).strip()


if __name__ == "__main__":  # pragma: no cover - manual/agent entry point
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Compile a .tex file or report engine status.")
    parser.add_argument("command", choices=("status", "compile"))
    parser.add_argument("path", nargs="?", help="the .tex file to compile")
    parser.add_argument("--out", help="where to write the PDF (default: alongside the source)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    if args.command == "status":
        print(engine_status())
        raise SystemExit(0)

    if not args.path:
        parser.error("compile needs a path")
    source_path = Path(args.path)
    out = Path(args.out) if args.out else source_path.with_suffix(".pdf")
    try:
        outcome = compile_pdf(source_path.read_text(encoding="utf-8"))
    except (LatexUnavailable, LatexCompileError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    out.write_bytes(outcome.pdf_bytes)
    print(f"wrote {out} in {outcome.duration_ms}ms with {outcome.engine}")
