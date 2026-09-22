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
    }


def save_resume(filename: str, content: bytes) -> dict[str, object]:
    """Write an uploaded resume to the project root and refresh the cache."""
    suffix = Path(filename).suffix.lower()
    if suffix not in (".pdf", ".txt", ".md"):
        raise ValueError(f"Unsupported resume format '{suffix}'. Use .pdf, .txt or .md.")

    target = PROJECT_ROOT / f"resume{suffix}"
    target.write_bytes(content)

    text = _extract(target)
    if not text:
        raise ValueError(f"Could not extract any text from {filename}.")

    updated_at = datetime.now(tz=timezone.utc).isoformat()
    _cache.update({"text": text, "filename": target.name, "updated_at": updated_at})
    set_setting("resume_filename", target.name)
    set_setting("resume_chars", str(len(text)))
    set_setting("resume_text", text)
    set_setting("resume_updated_at", updated_at)
    logger.info("Saved new resume %s (%d characters)", target.name, len(text))
    return resume_status()


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
