"""The in-app agent: a headless Claude Code session scoped to this project.

Design notes
------------
*Two phases per turn.* Every turn first runs read-only: the agent can read the
repo, query the database and use the web, but cannot change anything. If the task
needs changes it says so and ends with NEEDS_APPROVAL. Only after the owner
approves is the same conversation resumed with write permissions. This is how
"approve writes, auto-run reads" is enforced — not by trusting the model, but by
handing it a different permission set in each phase.

*Explicit denies.* An `allow` list alone does not disable the other tools in this
CLI, so every tool that could spawn a subagent, write a file or run an arbitrary
command is named in `deny`. Allow-listing is never relied on by itself.

*Git as the undo.* This project has no version control of its own, so the first
Engineer-mode change initialises a repository and every later one commits first.
A bad edit is then `git revert`-able rather than lost.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from claude_cli import ClaudeUnavailable, claude_available, claude_bin
from database import PROJECT_ROOT, get_db, get_setting

ARTIFACTS_DIR = PROJECT_ROOT / "data" / "walten-artifacts"
CONTEXT_DIR = PROJECT_ROOT / "data" / "walten-context"
PROMPT_TEMPLATE = Path(__file__).resolve().parent / "walten_prompt.md"

DEFAULT_NAME = "Walten"
MODES = ("assistant", "engineer")
APPROVAL_MARKER = "NEEDS_APPROVAL"

# Anything that could delegate work, reach outside the project, or act on its own
# schedule. Named explicitly because allow-listing does not disable the rest.
DENY_ALWAYS = [
    "Task", "Agent", "Workflow", "SendMessage", "ListAgents", "TaskStop",
    "Skill", "ToolSearch", "ScheduleWakeup", "CronCreate", "CronDelete", "CronList",
    "PushNotification", "ShareOnboardingGuide", "ReportFindings", "DesignSync",
    "EnterWorktree", "ExitWorktree", "EnterPlanMode", "ExitPlanMode",
    "NotebookEdit", "KillShell",
]

# Shells and interpreters that would make the command allow-list meaningless.
DENY_SHELLS = [
    "Bash(rm:*)", "Bash(rmdir:*)", "Bash(mv:*)", "Bash(cp:*)", "Bash(dd:*)",
    "Bash(chmod:*)", "Bash(chown:*)", "Bash(ln:*)", "Bash(tee:*)", "Bash(truncate:*)",
    "Bash(sh:*)", "Bash(bash:*)", "Bash(zsh:*)", "Bash(eval:*)", "Bash(exec:*)",
    "Bash(curl:*)", "Bash(wget:*)", "Bash(ssh:*)", "Bash(scp:*)", "Bash(nc:*)",
    "Bash(sqlite3:*)", "Bash(sudo:*)", "Bash(brew:*)", "Bash(pip:*)",
    "Bash(python:*)", "Bash(python3:*)",
]

READ_TOOLS = ["Read", "Glob", "Grep", "WebSearch", "WebFetch"]

# The only database access the agent gets: an audited, SELECT-only CLI.
DB_READ_COMMANDS = [
    "Bash(.venv/bin/python backend/walten_db.py query:*)",
    "Bash(.venv/bin/python backend/walten_db.py schema:*)",
]
DB_WRITE_COMMANDS = [
    "Bash(.venv/bin/python backend/walten_db.py update:*)",
    "Bash(.venv/bin/python backend/walten_db.py delete:*)",
]

# Scripts the agent may trigger in Assistant mode. Enumerated rather than allowing
# the interpreter, which would be equivalent to full shell access.
ASSISTANT_SCRIPTS = [
    "Bash(.venv/bin/python backend/scraper.py:*)",
    "Bash(.venv/bin/python backend/advisor.py:*)",
    "Bash(.venv/bin/python backend/source_discovery.py:*)",
    "Bash(.venv/bin/python backend/classifier.py:*)",
    "Bash(.venv/bin/python backend/resume_loader.py:*)",
]

# Honest note on what this list means. Build mode has to be able to run the
# project's own tooling, and `python`, `node` and `npm` are general-purpose: a
# script can do anything the process can, including starting another `claude`.
# So the guarantee here is "the harness's subagent and skill tools are denied in
# every mode and phase", not "the agent cannot run arbitrary code once a Build
# plan is approved". Assist mode, which gets named scripts instead of an
# interpreter, is the mode where the stronger claim holds.
ENGINEER_COMMANDS = [
    "Bash(.venv/bin/python:*)",
    "Bash(npm:*)", "Bash(npx:*)", "Bash(node:*)", "Bash(git:*)",
    "Bash(ls:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)",
]

# `Bash(git:*)` above is what lets Build mode inspect and commit its own work,
# but it would also hand it the commands that move or drop history — the same
# history the undo arrow in the transcript restores from. Deny wins over allow,
# so these are carved back out. Inspecting (status, diff, log, show) and
# recording (add, commit) all still work.
DENY_GIT = [
    "Bash(git reset:*)", "Bash(git checkout:*)", "Bash(git restore:*)",
    "Bash(git read-tree:*)", "Bash(git update-ref:*)", "Bash(git branch:*)",
    "Bash(git clean:*)", "Bash(git stash:*)", "Bash(git rebase:*)",
    "Bash(git filter-branch:*)", "Bash(git gc:*)", "Bash(git prune:*)",
    "Bash(git reflog expire:*)", "Bash(git push:*)",
    # `git config core.hooksPath` would get a script run on the next automatic
    # commit, which is a way back to execution that does not look like one.
    "Bash(git config:*)",
]


DEFAULT_ICON = "Dog"


def walten_name() -> str:
    return get_setting("walten_name") or DEFAULT_NAME


def walten_icon() -> str:
    return get_setting("walten_icon") or DEFAULT_ICON


def _artifact_globs() -> list[str]:
    relative = ARTIFACTS_DIR.relative_to(PROJECT_ROOT)
    return [f"Write({relative}/**)", f"Edit({relative}/**)"]


def build_policy(mode: str, phase: str) -> dict[str, Any]:
    """The permission set handed to the CLI for one turn."""
    allow = [*READ_TOOLS, *DB_READ_COMMANDS]
    deny = [*DENY_ALWAYS, *DENY_SHELLS, *DENY_GIT]

    if phase == "plan":
        # Read-only: no writing tools exist at all this turn.
        deny += ["Write", "Edit", "MultiEdit", *DB_WRITE_COMMANDS]
        return {"permissions": {"allow": allow, "deny": deny}}

    allow += [*DB_WRITE_COMMANDS, *_artifact_globs()]

    if mode == "engineer":
        # Source editing, package tooling and git. Still no subagents, still no
        # raw shells or network fetch tools beyond the allow-listed ones.
        allow += ["Write", "Edit", "MultiEdit", *ENGINEER_COMMANDS]
        deny = [rule for rule in deny if rule != "Bash(python:*)"]
    else:
        allow += ASSISTANT_SCRIPTS
        # Assistant may generate artifacts but never touch application source.
        deny += ["Write(backend/**)", "Edit(backend/**)",
                 "Write(frontend/**)", "Edit(frontend/**)",
                 "Write(scripts/**)", "Edit(scripts/**)",
                 "Write(.env)", "Edit(.env)"]

    return {"permissions": {"allow": allow, "deny": deny}}


MODE_DISPLAY = {"assistant": "Assist", "engineer": "Build"}

MODE_RULES = {
    "assistant": (
        "**Assist.** You organise and enrich what the tracker already has: "
        "query and tidy the database, re-tag and re-score listings, find and "
        "propose new sources, run the scraper and the advisor, and write reports "
        "or exports into `data/walten-artifacts/`.\n\n"
        "You cannot edit application source code, scripts or `.env` — those tools "
        "are disabled for you. If a task genuinely needs a code change, say so and "
        "tell the owner to switch you to Build mode."
    ),
    "engineer": (
        "**Build.** Everything Assist mode can do, plus editing the application's "
        "source, configuration and build tooling.\n\n"
        "The tree is committed to the checkpoint repo before every message, so the "
        "owner can rewind any turn — but that is a safety net, not a licence. "
        "Change the smallest thing that solves the problem, match the surrounding "
        "code's style, and never leave the app in a state that does not build.\n\n"
        "After editing anything under `frontend/src/`, run `npm run build` in "
        "`frontend/` — the server serves the compiled bundle, so an unbuilt change "
        "is invisible. Say whether you rebuilt."
    ),
}


def render_system_prompt(mode: str, context_files: list[str], context_urls: list[str]) -> str:
    lines: list[str] = []
    if context_files:
        lines.append("Files the owner attached — read them before starting:")
        lines += [f"- `{path}`" for path in context_files]
    if context_urls:
        lines.append("\nURLs the owner attached — fetch them when relevant:")
        lines += [f"- {url}" for url in context_urls]
    context_block = "\n".join(lines) if lines else "Nothing attached for this session."

    return PROMPT_TEMPLATE.read_text().format(
        name=walten_name(),
        project_root=PROJECT_ROOT,
        mode=MODE_DISPLAY.get(mode, mode.capitalize()),
        mode_rules=MODE_RULES.get(mode, MODE_RULES["assistant"]),
        context_block=context_block,
    )


# ------------------------------------------------------------------ git safety
#
# Every message you send commits the tree first, so the message itself becomes a
# restore point: the transcript records the commit, and the undo arrow beside a
# message puts the files back the way they were just before you sent it.
#
# These commits go into a repository of their own at `data/checkpoints.git`,
# *not* the project's `.git`. The working tree is shared but the history is not,
# so the owner's own branches and commits stay clean and `git pull` to upgrade
# never has to merge around hundreds of automatic commits.
#
# Undoing never rewrites history. The current state is committed, the old tree is
# read back in, and that rewind is committed on top — so an undo is an ordinary
# commit and nothing is ever unreachable.
#
# Only what the checkpoint repo tracks is covered, and its exclude list skips
# `data/` — so the database is *not* restored. Assist-mode work lives there and
# cannot be undone this way.

IDENTITY = ["-c", "user.name=Opportunity Tracker", "-c", "user.email=tracker@localhost"]

CHECKPOINT_DIR = PROJECT_ROOT / "data" / "checkpoints.git"

# The project's own .gitignore is still honoured on top of this; these are the
# paths the checkpoint repo must skip regardless of how the owner's is written.
CHECKPOINT_EXCLUDES = [
    "/.git/", "/data/", "/.venv/", "/venv/", "node_modules/", "__pycache__/",
    "*.pyc", "/frontend/dist/", "/logs/", ".DS_Store", "/.env",
]


def _git(*args: str) -> subprocess.CompletedProcess:
    """Run git against the checkpoint repo, with the project as its work tree."""
    return subprocess.run(
        ["git", f"--git-dir={CHECKPOINT_DIR}", f"--work-tree={PROJECT_ROOT}", *args],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
    )


def git_available() -> bool:
    return shutil.which("git") is not None


def has_repo() -> bool:
    return git_available() and CHECKPOINT_DIR.is_dir()


def ensure_repo() -> Optional[str]:
    """Create the checkpoint repository the first time an undo point is needed."""
    if not git_available():
        return "git is not installed; changes will have no undo"

    if not CHECKPOINT_DIR.is_dir():
        CHECKPOINT_DIR.parent.mkdir(parents=True, exist_ok=True)
        init = subprocess.run(
            ["git", "init", "-q", "--bare", str(CHECKPOINT_DIR)],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
        )
        if init.returncode != 0:
            return init.stderr.strip()[:200] or "could not create the checkpoint repository"

        # A bare repo has no work tree of its own; every call supplies one.
        # Telling it so up front keeps `git status` from refusing.
        _git("config", "core.bare", "false")
        _git("config", "core.worktree", str(PROJECT_ROOT))
        (CHECKPOINT_DIR / "info").mkdir(exist_ok=True)
        (CHECKPOINT_DIR / "info" / "exclude").write_text("\n".join(CHECKPOINT_EXCLUDES) + "\n")

    # The directory existing is not the same as the repo being usable: a first
    # attempt that found nothing to commit leaves it with no HEAD, and every
    # checkpoint taken against it would resolve to nothing. Lay the baseline
    # whenever it is missing, not only on the run that created the directory.
    if _rev("HEAD") is not None:
        return None

    _git("add", "-A")
    _git(*IDENTITY, "commit", "-q", "-m", "walten: baseline before first agent edit")
    if _rev("HEAD") is None:
        # Nothing was trackable, so no baseline commit exists and the repo has
        # no HEAD. Returning success here would hand out checkpoints pointing
        # at nothing, and the undo arrow would offer a restore that cannot run.
        return "nothing could be recorded as a baseline; changes will have no undo"

    # Restore points recorded before this repo existed name commits in whatever
    # repository was in use then — usually the project's own .git, from an
    # earlier version of this code. Those trees are unreachable from here, so
    # clear them rather than offering an undo that would fail on click.
    with get_db() as conn:
        conn.execute(
            "UPDATE walten_messages SET snapshot_sha = NULL, snapshot_tree = NULL "
            "WHERE snapshot_tree IS NOT NULL"
        )
    return None


def _rev(spec: str) -> Optional[str]:
    done = _git("rev-parse", "--verify", "--quiet", spec)
    return done.stdout.strip() or None


def working_state() -> dict[str, Any]:
    """The tree HEAD points at, and whether anything is uncommitted.

    Two cheap calls that settle, for the whole transcript at once, whether any
    given checkpoint still matches what is on disk. Commits are never empty, so
    "same tree and nothing uncommitted" means restoring it would be a no-op.
    """
    if not has_repo():
        return {"ok": False, "tree": None, "dirty": False}
    return {"ok": True, "tree": _rev("HEAD^{tree}"), "dirty": bool(_git("status", "--porcelain").stdout.strip())}


def checkpoint(label: str) -> dict[str, Any]:
    """Commit the tree as it stands and return the point it can be restored to."""
    warning = ensure_repo()
    if warning:
        return {"commit": None, "tree": None, "warning": warning}
    _git("add", "-A")
    done = _git(*IDENTITY, "commit", "-q", "-m", f"walten: before {label[:60]}")
    # Exit 1 is "nothing to commit" — HEAD already *is* the checkpoint.
    if done.returncode not in (0, 1):
        return {"commit": None, "tree": None, "warning": done.stderr.strip()[:200]}
    return {"commit": _rev("HEAD"), "tree": _rev("HEAD^{tree}"), "warning": None}


def snapshot(label: str) -> Optional[str]:
    """Back-compat wrapper: commit before an approved write, warning on failure."""
    return checkpoint(label).get("warning")


def changes_since(tree: Optional[str]) -> list[str]:
    """Paths that restoring `tree` would touch, uncommitted and untracked included."""
    if not tree or not has_repo() or _git("cat-file", "-e", f"{tree}^{{tree}}").returncode != 0:
        return []
    paths = _git("diff", "--name-only", tree, "--").stdout.splitlines()
    # Untracked files survive `read-tree`, but the restore commits everything
    # first, so by then they are tracked and the rewind removes them.
    paths += _git("ls-files", "--others", "--exclude-standard").stdout.splitlines()
    return sorted({line.strip() for line in paths if line.strip()})


def restore(tree: Optional[str], label: str) -> dict[str, Any]:
    """Put the working tree back to `tree`, keeping every commit reachable."""
    warning = ensure_repo()
    if warning:
        return {"ok": False, "error": warning}
    if not tree:
        return {"ok": False, "error": "This message has no restore point."}
    if _git("cat-file", "-e", f"{tree}^{{tree}}").returncode != 0:
        return {"ok": False, "error": "That restore point is no longer in the repository."}

    changed = changes_since(tree)
    if not changed:
        return {"ok": True, "changed": [], "commit": _rev("HEAD")}

    _git("add", "-A")
    _git(*IDENTITY, "commit", "-q", "-m", f"walten: before undo to {label[:50]}")
    reset = _git("read-tree", "-u", "--reset", tree)
    if reset.returncode != 0:
        return {"ok": False, "error": reset.stderr.strip()[:200] or "git read-tree failed"}
    done = _git(*IDENTITY, "commit", "-q", "-m", f"walten: undo to {label[:50]}")
    if done.returncode not in (0, 1):
        return {"ok": False, "error": done.stderr.strip()[:200]}
    return {"ok": True, "changed": changed, "commit": _rev("HEAD")}


# --------------------------------------------------------------------- running

@dataclass
class TurnState:
    """Live state for the turn currently running in one session."""

    session_id: int
    phase: str
    started_at: float = field(default_factory=time.monotonic)
    process: Optional[asyncio.subprocess.Process] = None
    events: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    cancelled: bool = False


RUNNING: dict[int, TurnState] = {}


def is_running(session_id: int) -> bool:
    return session_id in RUNNING


def live_state(session_id: int) -> Optional[dict[str, Any]]:
    turn = RUNNING.get(session_id)
    if turn is None:
        return None
    return {
        "phase": turn.phase,
        "elapsed_ms": int((time.monotonic() - turn.started_at) * 1000),
        "events": turn.events[-40:],
        "text": turn.text,
    }


async def cancel(session_id: int) -> bool:
    turn = RUNNING.get(session_id)
    if turn is None:
        return False
    turn.cancelled = True
    if turn.process and turn.process.returncode is None:
        turn.process.terminate()
        try:
            await asyncio.wait_for(turn.process.wait(), timeout=5)
        except asyncio.TimeoutError:
            turn.process.kill()
    return True


def _summarise_tool(name: str, payload: dict[str, Any]) -> str:
    """One readable line per tool call for the audit log."""
    if name == "Bash":
        return str(payload.get("command", ""))[:300]
    for key in ("file_path", "path", "pattern", "url", "query"):
        if payload.get(key):
            value = str(payload[key])
            if key == "file_path":
                try:
                    value = str(Path(value).relative_to(PROJECT_ROOT))
                except ValueError:
                    pass
            return value[:300]
    return json.dumps(payload, default=str)[:200]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def run_turn(
    *,
    session: dict[str, Any],
    prompt: str,
    phase: str,
    on_finish,
) -> None:
    """Run one turn of the conversation and hand the outcome to `on_finish`."""
    session_id = session["id"]
    mode = session["mode"]
    turn = TurnState(session_id=session_id, phase=phase)
    RUNNING[session_id] = turn

    outcome: dict[str, Any] = {
        "phase": phase, "content": "", "tool_calls": [], "error": None,
        "cost_usd": None, "duration_ms": None, "tokens_in": None, "tokens_out": None,
        "claude_session_id": session.get("claude_session_id"),
        "needs_approval": False,
    }

    settings_path = None
    prompt_path = None
    try:
        if not claude_available():
            raise ClaudeUnavailable("The claude CLI is not on PATH.")

        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        run_dir = PROJECT_ROOT / "data" / ".walten-run"
        run_dir.mkdir(parents=True, exist_ok=True)
        settings_path = run_dir / f"policy-{session_id}-{phase}.json"
        settings_path.write_text(json.dumps(build_policy(mode, phase), indent=2))
        prompt_path = run_dir / f"system-{session_id}.md"
        prompt_path.write_text(
            render_system_prompt(mode, json.loads(session.get("context_files") or "[]"),
                                 json.loads(session.get("context_urls") or "[]"))
        )

        cmd = [
            claude_bin(), "-p",
            "--output-format", "stream-json", "--verbose",
            "--model", session.get("model") or "sonnet",
            "--settings", str(settings_path),
            "--append-system-prompt-file", str(prompt_path),
        ]
        if session.get("claude_session_id"):
            cmd += ["--resume", session["claude_session_id"]]

        process = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=PROJECT_ROOT,
        )
        turn.process = process
        process.stdin.write(prompt.encode())
        await process.stdin.drain()
        process.stdin.close()

        async for raw in process.stdout:
            line = raw.decode(errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue

            kind = event.get("type")
            if kind == "system" and event.get("session_id"):
                outcome["claude_session_id"] = event["session_id"]
            elif kind == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "text":
                        turn.text += block.get("text", "")
                    elif block.get("type") == "tool_use":
                        entry = {
                            "tool": block.get("name"),
                            "detail": _summarise_tool(block.get("name", ""), block.get("input") or {}),
                            "at": _now(),
                        }
                        outcome["tool_calls"].append(entry)
                        turn.events.append(entry)
            elif kind == "result":
                if event.get("result"):
                    turn.text = event["result"]
                outcome["cost_usd"] = event.get("total_cost_usd")
                outcome["duration_ms"] = event.get("duration_ms") or event.get("duration_api_ms")
                usage = event.get("usage") or {}
                outcome["tokens_in"] = usage.get("input_tokens")
                outcome["tokens_out"] = usage.get("output_tokens")
                if event.get("session_id"):
                    outcome["claude_session_id"] = event["session_id"]
                if event.get("is_error"):
                    outcome["error"] = str(event.get("result"))[:800]

        stderr = (await process.stderr.read()).decode(errors="replace").strip()
        await process.wait()

        if turn.cancelled:
            outcome["error"] = "Stopped."
        elif process.returncode != 0 and not turn.text:
            outcome["error"] = stderr[-800:] or f"claude exited {process.returncode}"

    except Exception as exc:  # surfaced in the transcript rather than swallowed
        outcome["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        RUNNING.pop(session_id, None)
        for path in (settings_path, prompt_path):
            if path and path.exists():
                path.unlink(missing_ok=True)

    outcome["content"] = turn.text.strip()
    # Only a read-only turn can ask for approval; an apply turn has already run.
    outcome["needs_approval"] = (
        phase == "plan"
        and not outcome["error"]
        and APPROVAL_MARKER in outcome["content"]
    )
    outcome["content"] = outcome["content"].replace(APPROVAL_MARKER, "").rstrip()
    on_finish(outcome)
