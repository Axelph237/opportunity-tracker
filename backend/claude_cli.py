"""Thin wrapper around the local `claude` CLI running in headless (-p) mode.

The project deliberately avoids the Anthropic Python SDK: every Claude call is a
one-shot `claude -p` subprocess that reuses the user's existing CLI login, so no
ANTHROPIC_API_KEY is required anywhere in this codebase.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from typing import Any, Optional, Sequence

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

ENV_CLAUDE_BIN = os.getenv("CLAUDE_BIN", "claude")


def claude_bin() -> str:
    """Where the CLI lives: the saved setting wins, then .env, then PATH.

    Onboarding writes the setting when the binary is not on PATH, so a manual
    path survives without the user having to edit .env.
    """
    try:
        from database import get_setting

        return get_setting("claude_bin") or ENV_CLAUDE_BIN
    except Exception:
        return ENV_CLAUDE_BIN


# Kept for callers that only need the default; prefer claude_bin().
CLAUDE_BIN = ENV_CLAUDE_BIN
DEFAULT_MODEL = os.getenv("CLAUDE_MODEL", "sonnet")
DEFAULT_TIMEOUT = int(os.getenv("CLAUDE_TIMEOUT_SECONDS", "240"))

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class ClaudeUnavailable(RuntimeError):
    """Raised when the `claude` CLI is missing or cannot be executed."""


class ClaudeCallError(RuntimeError):
    """Raised when the CLI runs but returns an error or unusable output."""


def claude_available(path: Optional[str] = None) -> bool:
    binary = path or claude_bin()
    return shutil.which(binary) is not None or os.path.isfile(binary)


def claude_version(path: Optional[str] = None) -> Optional[str]:
    """Run `--version` to prove the binary actually works, not just that it exists."""
    binary = path or claude_bin()
    if not claude_available(binary):
        return None
    try:
        done = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def _resolve_model(model: Optional[str]) -> str:
    if model:
        return model
    try:
        from database import get_setting

        return get_setting("model") or DEFAULT_MODEL
    except Exception:
        return DEFAULT_MODEL


def run_claude(
    prompt: str,
    *,
    system: Optional[str] = None,
    model: Optional[str] = None,
    allowed_tools: Optional[Sequence[str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
    cwd: Optional[str] = None,
) -> str:
    """Run one headless Claude turn and return its final text response.

    `allowed_tools` pre-approves tools (e.g. ["WebSearch", "WebFetch"]). When it
    is empty the session runs `--restricted`, which strips the command-running
    tools entirely — the right shape for pure text classification.
    """
    if not claude_available():
        raise ClaudeUnavailable(
            f"`{claude_bin()}` was not found on PATH. Install Claude Code or set the path in Settings."
        )

    cmd: list[str] = [claude_bin(), "-p", "--output-format", "json", "--model", _resolve_model(model)]
    if system:
        cmd += ["--system-prompt", system]
    if allowed_tools:
        cmd += ["--allowedTools", ",".join(allowed_tools), "--permission-mode", "dontAsk"]
    else:
        cmd += ["--restricted"]

    logger.debug("Running claude: %s", " ".join(cmd[:8]))
    try:
        proc = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        raise ClaudeCallError(f"claude timed out after {timeout}s") from exc
    except OSError as exc:
        raise ClaudeUnavailable(f"Could not execute `{CLAUDE_BIN}`: {exc}") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[:500]
        raise ClaudeCallError(f"claude exited with code {proc.returncode}: {detail}")

    stdout = (proc.stdout or "").strip()
    if not stdout:
        raise ClaudeCallError("claude returned no output")

    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        # --output-format json should always yield JSON, but tolerate plain text.
        return stdout

    if isinstance(envelope, dict):
        if envelope.get("is_error"):
            raise ClaudeCallError(str(envelope.get("result") or "claude reported an error"))
        result = envelope.get("result")
        if isinstance(result, str):
            return result.strip()
    return stdout


def extract_json(text: str) -> Any:
    """Pull the first JSON object or array out of a model response."""
    if not text:
        raise ValueError("empty response")

    candidates: list[str] = []
    fenced = _FENCE_RE.search(text)
    if fenced:
        candidates.append(fenced.group(1).strip())
    candidates.append(text.strip())

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        for opener, closer in (("{", "}"), ("[", "]")):
            start = candidate.find(opener)
            end = candidate.rfind(closer)
            if start != -1 and end > start:
                try:
                    return json.loads(candidate[start : end + 1])
                except json.JSONDecodeError:
                    continue

    raise ValueError(f"no JSON found in response: {text[:200]!r}")


def run_claude_json(prompt: str, **kwargs: Any) -> Any:
    """Run a headless turn and parse the response as JSON."""
    return extract_json(run_claude(prompt, **kwargs))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"claude available: {claude_available()}")
    print(run_claude_json('Return only this JSON: {"ok": true, "n": 3}'))
