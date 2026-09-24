"""Saved resume variants: storage, compilation and the link to listings.

An *instance* is one tailored version of the resume — "Base", "Quantum labs",
"IBM internship" — kept as LaTeX source. Each compiles to its own PDF under
`data/resumes/`, and any listing can point at the instance written for it.

Exactly one instance can be the default, meaning its render is the document the
scraper scores against. That keeps a single answer to "which resume is this app
comparing listings to" even when a dozen variants exist.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import latex
import latex_compat
from database import PROJECT_ROOT, get_db
from resume_loader import publish_render, resume_status, resume_tex, text_for_render

logger = logging.getLogger(__name__)

RESUMES_DIR = PROJECT_ROOT / "data" / "resumes"

# Images and include files every version compiles against. Shared rather than
# per-version: a seal or a headshot belongs to the person, not to one tailored
# variant, and making each copy own its own would mean re-uploading the same
# logo for every job applied to.
ASSETS_DIR = PROJECT_ROOT / "data" / "resume-assets"

MAX_NAME_LENGTH = 120

# What a resume can legitimately pull in. Executable and archive formats are
# absent on purpose: these files are staged next to the source in the compile
# directory, and the engine is told to read from there.
ASSET_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".pdf", ".eps", ".gif", ".webp",
    ".tex", ".sty", ".cls", ".bib", ".bst",
}
MAX_ASSET_BYTES = 10_000_000

STARTER_TEMPLATE = r"""\documentclass[letterpaper,11pt]{article}

\usepackage[margin=0.75in]{geometry}
\usepackage{enumitem}
\usepackage{titlesec}
\usepackage[hidelinks]{hyperref}

\pagestyle{empty}
\titleformat{\section}{\large\bfseries}{}{0pt}{}[\titlerule]
\titlespacing{\section}{0pt}{12pt}{6pt}
\setlist[itemize]{leftmargin=*, topsep=2pt, itemsep=1pt}

\newcommand{\entry}[4]{%
  \textbf{#1} \hfill #2 \\
  \textit{#3} \hfill \textit{#4}%
}

\begin{document}

\begin{center}
  {\LARGE \textbf{Your Name}} \\[4pt]
  city, state $\cdot$ you@example.com $\cdot$ (000) 000-0000 \\
  \href{https://github.com/you}{github.com/you} $\cdot$
  \href{https://linkedin.com/in/you}{linkedin.com/in/you}
\end{center}

\section{Education}
\entry{University Name}{City, State}{B.S. in Your Major}{Expected May 2027}
\begin{itemize}
  \item Relevant coursework: one, two, three.
\end{itemize}

\section{Experience}
\entry{Organization}{City, State}{Your Title}{Jun 2025 -- Aug 2025}
\begin{itemize}
  \item What you built, and the number that shows it mattered.
  \item A second bullet, led with the verb and ended with the result.
\end{itemize}

\section{Projects}
\entry{Project Name}{}{Tools you used}{2025}
\begin{itemize}
  \item What it does and why you made it.
\end{itemize}

\section{Skills}
\textbf{Languages:} Python, C++ \\
\textbf{Tools:} Git, Docker

\end{document}
"""


class ResumeNotFound(LookupError):
    """Raised when an instance id does not exist."""


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _json_list(value: Any) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def instance_dict(row: sqlite3.Row, *, include_latex: bool = True) -> dict[str, Any]:
    data = dict(row)
    data["is_default"] = bool(data.get("is_default"))
    data["compile_ok"] = bool(data.get("compile_ok"))
    data["compile_errors"] = _json_list(data.get("compile_errors"))
    data["has_pdf"] = bool(data.get("pdf_filename")) and pdf_path(data).is_file()
    data["issues"] = latex_compat.check(data.get("latex")) if include_latex else []
    if not include_latex:
        # The list view renders a dozen rows; shipping every document with it
        # would be megabytes for a sidebar that shows names and dates.
        data.pop("latex", None)
        data.pop("compile_log", None)
    return data


def pdf_path(instance: dict[str, Any]) -> Path:
    name = instance.get("pdf_filename") or f"resume-{instance['id']}.pdf"
    return RESUMES_DIR / name


def list_instances() -> list[dict[str, Any]]:
    """Every saved variant, newest default first, with its listing count."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT r.*, (
                   SELECT COUNT(*) FROM opportunities o WHERE o.resume_instance_id = r.id
               ) AS linked_count
               FROM resume_instances r
               ORDER BY r.is_default DESC, r.updated_at DESC, r.id DESC"""
        ).fetchall()
    return [instance_dict(row, include_latex=False) for row in rows]


def get_instance(instance_id: int) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(
            """SELECT r.*, (
                   SELECT COUNT(*) FROM opportunities o WHERE o.resume_instance_id = r.id
               ) AS linked_count
               FROM resume_instances r WHERE r.id = ?""",
            (instance_id,),
        ).fetchone()
    if row is None:
        raise ResumeNotFound(f"Resume {instance_id} not found")
    return instance_dict(row)


def default_instance() -> Optional[dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM resume_instances WHERE is_default = 1 LIMIT 1"
        ).fetchone()
    return instance_dict(row) if row else None


def starting_source(copy_from: Optional[int] = None) -> str:
    """What a new instance opens with.

    An explicit copy wins, then the uploaded `resume.tex`, then the default
    instance, and only then the starter template — so a user who has already
    given the app their real resume never starts from a stranger's.
    """
    if copy_from is not None:
        return get_instance(copy_from)["latex"]
    uploaded = resume_tex()
    if uploaded and uploaded.strip():
        return uploaded
    existing = default_instance()
    if existing and existing["latex"].strip():
        return existing["latex"]
    return STARTER_TEMPLATE


def _unique_name(conn: sqlite3.Connection, name: str) -> str:
    """Append a counter until the name is free. Names are how the user tells
    variants apart in a dropdown, so two called "Base" would be a trap."""
    taken = {row["name"] for row in conn.execute("SELECT name FROM resume_instances")}
    if name not in taken:
        return name
    for counter in range(2, 1000):
        candidate = f"{name} {counter}"
        if candidate not in taken:
            return candidate
    return f"{name} {datetime.now().timestamp():.0f}"


def create_instance(
    name: str,
    *,
    description: Optional[str] = None,
    latex_source: Optional[str] = None,
    copy_from: Optional[int] = None,
) -> dict[str, Any]:
    source = latex_source if latex_source is not None else starting_source(copy_from)
    clean = (name or "").strip()[:MAX_NAME_LENGTH] or "Untitled resume"
    # Read outside the transaction below: resume_status() opens its own
    # connection, and nesting one inside an open write is how deadlocks start.
    already_scoring = resume_status()["loaded"]
    with get_db() as conn:
        unique = _unique_name(conn, clean)
        # The very first version takes over scoring only when nothing is being
        # scored yet. A user who already uploaded a resume should not find it
        # replaced by a template the moment they open the editor — switching is
        # what "Use for scoring" is for.
        first = (
            conn.execute("SELECT COUNT(*) AS c FROM resume_instances").fetchone()["c"] == 0
            and not already_scoring
        )
        cursor = conn.execute(
            """INSERT INTO resume_instances (name, description, latex, is_default, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (unique, description, source, int(first), _now(), _now()),
        )
        instance_id = int(cursor.lastrowid)
    return get_instance(instance_id)


EDITABLE_FIELDS = ("name", "description", "latex")


def update_instance(instance_id: int, values: dict[str, Any]) -> dict[str, Any]:
    changes = {key: value for key, value in values.items() if key in EDITABLE_FIELDS}
    if "name" in changes:
        cleaned = (changes["name"] or "").strip()[:MAX_NAME_LENGTH]
        if not cleaned:
            raise ValueError("A resume needs a name.")
        changes["name"] = cleaned
    if not changes:
        return get_instance(instance_id)

    with get_db() as conn:
        if conn.execute("SELECT 1 FROM resume_instances WHERE id = ?", (instance_id,)).fetchone() is None:
            raise ResumeNotFound(f"Resume {instance_id} not found")
        if "name" in changes:
            clash = conn.execute(
                "SELECT 1 FROM resume_instances WHERE name = ? AND id != ?",
                (changes["name"], instance_id),
            ).fetchone()
            if clash:
                raise ValueError(f"Another resume is already called “{changes['name']}”.")
        assignments = ", ".join(f"{column} = ?" for column in changes)
        conn.execute(
            f"UPDATE resume_instances SET {assignments}, updated_at = ? WHERE id = ?",
            [*changes.values(), _now(), instance_id],
        )
    return get_instance(instance_id)


def delete_instance(instance_id: int) -> None:
    instance = get_instance(instance_id)
    with get_db() as conn:
        # Explicit rather than trusting ON DELETE SET NULL: databases upgraded
        # from an earlier version carry the column without the foreign key.
        conn.execute(
            "UPDATE opportunities SET resume_instance_id = NULL WHERE resume_instance_id = ?",
            (instance_id,),
        )
        conn.execute("DELETE FROM resume_instances WHERE id = ?", (instance_id,))
        if instance["is_default"]:
            # Promote the next one so "which resume gets scored" keeps an answer.
            successor = conn.execute(
                "SELECT id FROM resume_instances ORDER BY updated_at DESC, id DESC LIMIT 1"
            ).fetchone()
            if successor:
                conn.execute(
                    "UPDATE resume_instances SET is_default = 1 WHERE id = ?", (successor["id"],)
                )
    artifact = pdf_path(instance)
    if artifact.is_file():
        artifact.unlink(missing_ok=True)


def set_default(instance_id: int) -> dict[str, Any]:
    """Make this the variant the scraper scores against."""
    instance = get_instance(instance_id)
    with get_db() as conn:
        conn.execute("UPDATE resume_instances SET is_default = 0 WHERE is_default = 1")
        conn.execute("UPDATE resume_instances SET is_default = 1 WHERE id = ?", (instance_id,))
    _publish(instance)
    return get_instance(instance_id)


def _publish(instance: dict[str, Any]) -> None:
    """Push a default instance out to the document the rest of the app scores.

    Failures here are logged, not raised: the user asked to switch resumes, and
    a variant that does not compile yet should still become the selected one.
    """
    artifact = pdf_path(instance)
    source = instance.get("latex") or ""
    try:
        if instance.get("compile_ok") and artifact.is_file():
            rendered = artifact.read_bytes()
            publish_render(rendered, text_for_render(source, rendered))
            return
        text = latex.strip_latex(source)
        if text:
            publish_render(None, text)
    except Exception as exc:
        logger.warning("Could not publish resume %s for scoring: %s", instance.get("id"), exc)


def compile_instance(instance_id: int) -> dict[str, Any]:
    """Render an instance to PDF and record how it went.

    A compile failure is a normal outcome here, not an exception: the editor
    needs the log and the line numbers to show the user what to fix. Only a
    missing engine propagates, because that is a setup problem rather than a
    problem with the document.
    """
    instance = get_instance(instance_id)
    RESUMES_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"resume-{instance_id}.pdf"

    ok, log, errors = True, "", []
    try:
        result = latex.compile_pdf(instance["latex"], assets=asset_paths())
        (RESUMES_DIR / filename).write_bytes(result.pdf_bytes)
        log, errors = result.log, result.errors
    except latex.LatexCompileError as exc:
        ok, log, errors = False, exc.log, exc.errors or [{"line": None, "message": str(exc)}]

    with get_db() as conn:
        conn.execute(
            """UPDATE resume_instances
               SET pdf_filename = ?, compiled_at = ?, compile_ok = ?, compile_log = ?, compile_errors = ?
               WHERE id = ?""",
            (
                filename if ok else instance.get("pdf_filename"),
                _now(),
                int(ok),
                log[-20_000:],  # a runaway log is not worth storing in full
                json.dumps(errors),
                instance_id,
            ),
        )

    updated = get_instance(instance_id)
    if updated["is_default"] and ok:
        _publish(updated)
    return updated


# ---------------------------------------------------------------------- assets

class AssetError(ValueError):
    """Raised when an upload is not something a resume may include."""


def safe_asset_name(filename: str) -> str:
    """Reduce an uploaded filename to a bare, safe name.

    Everything before the last separator is discarded, so `../../.ssh/id_rsa`
    and `C:\\keys\\id_rsa` both collapse to a leaf name that cannot escape the
    assets directory. The result is re-checked by the caller against a resolved
    path, because a sanitiser alone is a single point of failure.
    """
    leaf = filename.replace("\\", "/").rsplit("/", 1)[-1].strip()
    # A leading dot would make the file invisible and, for names like `.`
    # and `..`, meaningless as a target.
    leaf = leaf.lstrip(".")
    if not leaf:
        raise AssetError("That file has no usable name.")
    suffix = Path(leaf).suffix.lower()
    if suffix not in ASSET_SUFFIXES:
        allowed = ", ".join(sorted(ASSET_SUFFIXES))
        raise AssetError(f"'{suffix or leaf}' is not a supported asset. Use one of: {allowed}.")
    # Trim the stem, never the extension: truncating the whole name would drop
    # the suffix that was just checked and save a file of a different type
    # than the one that passed validation.
    stem = Path(leaf).stem[: MAX_NAME_LENGTH - len(suffix)]
    return f"{stem}{suffix}"


def _asset_path(name: str) -> Path:
    """Resolve a name inside the assets directory, or refuse.

    The belt to `safe_asset_name`'s braces: whatever the name looked like, the
    resolved path has to sit directly in the assets directory.
    """
    target = (ASSETS_DIR / safe_asset_name(name)).resolve()
    if target.parent != ASSETS_DIR.resolve():
        raise AssetError("That path is not inside the assets directory.")
    return target


def list_assets() -> list[dict[str, Any]]:
    """Every uploaded asset, newest first."""
    if not ASSETS_DIR.is_dir():
        return []
    entries = []
    for path in ASSETS_DIR.iterdir():
        if not path.is_file() or path.name.startswith("."):
            continue
        stat = path.stat()
        entries.append(
            {
                "name": path.name,
                "size": stat.st_size,
                "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    entries.sort(key=lambda entry: entry["updated_at"], reverse=True)
    return entries


def save_asset(filename: str, content: bytes) -> dict[str, Any]:
    if not content:
        raise AssetError("That file is empty.")
    if len(content) > MAX_ASSET_BYTES:
        raise AssetError(f"Assets are limited to {MAX_ASSET_BYTES // 1_000_000} MB.")
    target = _asset_path(filename)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    logger.info("Saved resume asset %s (%d bytes)", target.name, len(content))
    stat = target.stat()
    return {
        "name": target.name,
        "size": stat.st_size,
        "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }


def delete_asset(name: str) -> None:
    target = _asset_path(name)
    if not target.is_file():
        raise ResumeNotFound(f"No asset called {target.name}")
    target.unlink()
    logger.info("Deleted resume asset %s", target.name)


def asset_paths() -> list[Path]:
    """The files to stage beside the source on the next compile."""
    if not ASSETS_DIR.is_dir():
        return []
    return [path for path in sorted(ASSETS_DIR.iterdir()) if path.is_file() and not path.name.startswith(".")]


def fix_instance(instance_id: int, ids: Optional[list[str]] = None) -> dict[str, Any]:
    """Apply the compatibility fixes to a version's source.

    Writes through `update_instance` so the edit is an ordinary save: it shows
    up in the editor as the document it now is, rather than as something the
    compiler did behind the user's back.
    """
    instance = get_instance(instance_id)
    fixed, applied = latex_compat.apply_fixes(instance["latex"], ids)
    if not applied:
        return instance
    return update_instance(instance_id, {"latex": fixed})


def linked_opportunities(instance_id: int) -> list[dict[str, Any]]:
    """Listings this resume is attached to, with any advice already generated."""
    get_instance(instance_id)  # 404 for an unknown id rather than an empty list
    with get_db() as conn:
        rows = conn.execute(
            """SELECT o.id, o.title, o.organization, o.url, o.deadline, o.relevance_score,
                      adv.generated_at AS advice_generated_at
               FROM opportunities o
               LEFT JOIN resume_advice adv ON adv.opportunity_id = o.id
               WHERE o.resume_instance_id = ?
               ORDER BY CASE WHEN o.relevance_score IS NULL THEN 1 ELSE 0 END ASC,
                        o.relevance_score DESC, o.id DESC""",
            (instance_id,),
        ).fetchall()
    return [dict(row) for row in rows]
