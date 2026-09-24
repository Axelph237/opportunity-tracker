"""Loads the user's resume from the project root and caches its text."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from database import PROJECT_ROOT, get_setting, set_setting

load_dotenv()

logger = logging.getLogger(__name__)

CANDIDATE_NAMES = ("resume.pdf", "resume.txt", "resume.md")
MIN_USEFUL_CHARS = 200

# The LaTeX source lives beside the rendered document rather than in the
# candidate list: .tex is what the editor edits, the PDF it compiles to is what
# gets scored. Only when no engine is installed does the source itself become
# the text, and then by way of strip_latex rather than by being read raw.
TEX_NAME = "resume.tex"

# Where a render is published to. Deliberately *not* `resume.pdf`: that name
# belongs to whatever the user uploaded, and silently overwriting it the first
# time a resume version compiles would destroy the document they gave us.
ACTIVE_BASENAME = "resume-active"

_cache: dict[str, Optional[str]] = {"text": None, "filename": None, "updated_at": None}


def _extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover - dependency is declared in requirements.txt
        logger.warning("pypdf is not installed; cannot read %s", path.name)
        return ""
    try:
        reader = PdfReader(str(path))
        pages = [(page.extract_text() or "") for page in reader.pages]
        return "\n".join(pages).strip()
    except Exception as exc:
        logger.warning("Failed to extract text from %s: %s", path.name, exc)
        return ""


def _extract(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return _extract_pdf(path)
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception as exc:
        logger.warning("Failed to read %s: %s", path.name, exc)
        return ""


def _candidate_paths() -> list[Path]:
    paths: list[Path] = []
    # A file uploaded through the API wins over RESUME_PATH, otherwise uploading
    # resume.txt while resume.pdf still sits in the root would be lost on restart.
    try:
        uploaded = get_setting("resume_filename")
    except Exception:
        uploaded = None
    if uploaded:
        paths.append(PROJECT_ROOT / uploaded)

    env_path = os.getenv("RESUME_PATH")
    if env_path:
        candidate = Path(env_path)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        paths.append(candidate)
    paths.extend(PROJECT_ROOT / name for name in CANDIDATE_NAMES)
    # De-duplicate while preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def load_resume(force: bool = False) -> Optional[str]:
    """Find, extract and cache the resume text. Returns None when none is found."""
    if _cache["text"] and not force:
        return _cache["text"]

    best_text, best_path = "", None
    for path in _candidate_paths():
        if not path.exists() or not path.is_file():
            continue
        text = _extract(path)
        if len(text) > len(best_text):
            best_text, best_path = text, path
        # A PDF that extracted cleanly is good enough; stop early.
        if len(best_text) >= MIN_USEFUL_CHARS:
            break

    if not best_text or best_path is None:
        logger.warning(
            "No resume found in %s (looked for %s). Scraping will still run, but "
            "relevance scoring will be skipped.",
            PROJECT_ROOT,
            ", ".join(CANDIDATE_NAMES),
        )
        _cache.update({"text": None, "filename": None, "updated_at": None})
        return None

    updated_at = datetime.fromtimestamp(best_path.stat().st_mtime, tz=timezone.utc).isoformat()
    _cache.update({"text": best_text, "filename": best_path.name, "updated_at": updated_at})
    try:
        set_setting("resume_filename", best_path.name)
        set_setting("resume_chars", str(len(best_text)))
        set_setting("resume_text", best_text)
        set_setting("resume_updated_at", updated_at)
    except Exception as exc:  # the DB may not be initialised yet during early imports
        logger.debug("Could not persist resume cache: %s", exc)

    logger.info("Loaded resume from %s (%d characters)", best_path.name, len(best_text))
    return best_text


def get_resume_text() -> Optional[str]:
    """Return the cached resume text, loading it (or restoring it from SQLite) on demand."""
    if _cache["text"]:
        return _cache["text"]
    text = load_resume()
    if text:
        return text
    stored = get_setting("resume_text")
    if stored:
        _cache.update(
            {
                "text": stored,
                "filename": get_setting("resume_filename"),
                "updated_at": get_setting("resume_updated_at"),
            }
        )
        return stored
    return None


def resume_status() -> dict[str, object]:
    text = get_resume_text()
    return {
        "loaded": bool(text),
        "filename": _cache["filename"] or get_setting("resume_filename"),
        "characters": len(text) if text else 0,
        "updated_at": _cache["updated_at"] or get_setting("resume_updated_at"),
        "tex": resume_tex_status(),
    }


def publish_resume(target: Path, content: bytes, text: str) -> dict[str, object]:
    """Write the document that gets scored, and point the cache at it.

    Callers pass the text rather than having it re-extracted here, because the
    caller often knows better: a LaTeX render whose fonts pypdf cannot map
    extracts as nothing, and the stripped source is a far better reading of it
    than a second failed extraction would be.
    """
    if not text.strip():
        raise ValueError(f"Could not extract any text from {target.name}.")

    target.write_bytes(content)
    updated_at = datetime.now(tz=timezone.utc).isoformat()
    _cache.update({"text": text, "filename": target.name, "updated_at": updated_at})
    set_setting("resume_filename", target.name)
    set_setting("resume_chars", str(len(text)))
    set_setting("resume_text", text)
    set_setting("resume_updated_at", updated_at)
    logger.info("Saved new resume %s (%d characters)", target.name, len(text))
    return resume_status()


def save_resume(filename: str, content: bytes) -> dict[str, object]:
    """Write an uploaded resume to the project root and refresh the cache."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".tex":
        # A .tex upload is a source file, not a document: it is stored as the
        # LaTeX source and rendered, and the render is what gets scored.
        return save_resume_tex(content.decode("utf-8", errors="replace"))
    if suffix not in (".pdf", ".txt", ".md"):
        raise ValueError(f"Unsupported resume format '{suffix}'. Use .pdf, .tex, .txt or .md.")

    target = PROJECT_ROOT / f"resume{suffix}"
    target.write_bytes(content)
    text = _extract(target)
    if not text:
        raise ValueError(f"Could not extract any text from {filename}.")
    return publish_resume(target, content, text)


# ----------------------------------------------------------------- LaTeX source

def tex_path() -> Path:
    return PROJECT_ROOT / TEX_NAME


def resume_tex() -> Optional[str]:
    """The stored LaTeX source, or None when the user has not supplied one."""
    path = tex_path()
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.warning("Could not read %s: %s", path.name, exc)
        return None


def resume_tex_status() -> dict[str, object]:
    source = resume_tex()
    path = tex_path()
    updated_at = None
    if path.is_file():
        updated_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    import latex_compat

    return {
        "present": source is not None,
        "filename": TEX_NAME if source is not None else None,
        "characters": len(source) if source else 0,
        "updated_at": updated_at,
        # Surfaced at import so an uploaded template offers its fix before the
        # user ever meets a red compile error.
        "issues": latex_compat.check(source),
    }


def pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes. Returns "" rather than raising."""
    try:
        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(pdf_bytes))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:
        logger.warning("Could not extract text from the rendered PDF: %s", exc)
        return ""


def text_for_render(source: str, pdf_bytes: Optional[bytes]) -> str:
    """The best reading of a resume given its source and, maybe, its render.

    A PDF whose fonts pypdf cannot map extracts as gibberish or as nothing at
    all, which would quietly wreck every relevance score. Whenever the render
    yields less than the stripped source does, the source wins.
    """
    import latex

    text = pdf_text(pdf_bytes) if pdf_bytes else ""
    if len(text) >= MIN_USEFUL_CHARS:
        return text
    stripped = latex.strip_latex(source)
    return stripped if len(stripped) > len(text) else text


def render_tex_to_text(source: str) -> tuple[Optional[bytes], str]:
    """Render LaTeX source, returning `(pdf_bytes, text)`.

    With an engine installed the PDF is authoritative and its extracted text is
    what gets scored. Without one — or when the source does not compile — the
    markup is stripped instead, so an uncompilable draft still beats scoring
    against nothing.
    """
    import latex

    try:
        result = latex.compile_pdf(source)
    except (latex.LatexUnavailable, latex.LatexCompileError) as exc:
        logger.info("Falling back to stripped LaTeX text: %s", exc)
        return None, latex.strip_latex(source)

    return result.pdf_bytes, text_for_render(source, result.pdf_bytes)


def fix_resume_tex(ids: Optional[list[str]] = None) -> dict[str, object]:
    """Apply the compatibility fixes to the stored LaTeX source and re-render."""
    import latex_compat

    source = resume_tex()
    if not source:
        raise ValueError("No LaTeX source has been uploaded yet.")
    fixed, applied = latex_compat.apply_fixes(source, ids)
    if not applied:
        return resume_status()
    return save_resume_tex(fixed)


def save_resume_tex(source: str) -> dict[str, object]:
    """Store LaTeX source as the resume and make its render the scored document."""
    if not source.strip():
        raise ValueError("The LaTeX source is empty.")

    tex_path().write_text(source, encoding="utf-8")
    set_setting("resume_tex_updated_at", datetime.now(tz=timezone.utc).isoformat())

    pdf_bytes, text = render_tex_to_text(source)
    if not text:
        raise ValueError("Could not get any text out of that LaTeX source.")

    return publish_render(pdf_bytes, text)


def publish_render(pdf_bytes: Optional[bytes], text: str) -> dict[str, object]:
    """Make a rendered resume the document everything is scored against.

    Written under `resume-active.*` so the file the user uploaded is left
    untouched. The counterpart is removed when the format changes, so a stale
    `.txt` cannot outlive the `.pdf` that replaced it.
    """
    suffix = ".pdf" if pdf_bytes else ".txt"
    stale = PROJECT_ROOT / f"{ACTIVE_BASENAME}{'.txt' if pdf_bytes else '.pdf'}"
    if stale.is_file():
        stale.unlink(missing_ok=True)
    target = PROJECT_ROOT / f"{ACTIVE_BASENAME}{suffix}"
    return publish_resume(target, pdf_bytes or text.encode("utf-8"), text)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from database import init_db

    init_db()
    status = resume_status()
    print(status)
    text = get_resume_text()
    if text:
        print("--- first 400 characters ---")
        print(text[:400])
