"""Shared fixtures for the backend test suite.

Hard isolation rules enforced here:

* No test may ever open the real ``data/opportunities.db``. ``DB_PATH`` is
  monkeypatched to a fresh temp file before every test that touches the
  database (see ``db_path`` / ``app_client``), and the *first* import of
  ``database`` in this whole process (which happens when this file is
  imported, before any test module) already sees a temp path because we set
  the ``DB_PATH`` environment variable at module import time, below.
* No test may ever shell out to the real ``claude`` CLI. ``_never_call_real_claude``
  replaces every module-local binding of the claude_cli entry points with a
  safe stub, for every test, automatically.
* Walten's git checkpoint repository must never be created inside the real
  project. Tests that exercise it request the ``walten_tmp`` fixture, which
  points ``walten.PROJECT_ROOT`` / ``walten.CHECKPOINT_DIR`` /
  ``walten.ARTIFACTS_DIR`` / ``walten.CONTEXT_DIR`` at a temp directory.
"""

from __future__ import annotations

import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

# ---------------------------------------------------------------------------
# This MUST happen before `database` (or anything that imports it) is loaded
# for the first time in this process, so that even the very first `init_db()`
# call (e.g. from a FastAPI lifespan) lands on a temp file rather than the
# real project database.
_SESSION_TMP = Path(tempfile.mkdtemp(prefix="opening-finder-tests-"))
os.environ.setdefault("DB_PATH", str(_SESSION_TMP / "session-default.db"))

import pytest
from fastapi.testclient import TestClient

import advisor
import classifier
import claude_cli
import database
import main
import source_discovery
import walten

BACKEND_DIR = Path(__file__).resolve().parent.parent
REAL_PROJECT_ROOT = database.PROJECT_ROOT
REAL_DB_PATH = REAL_PROJECT_ROOT / "data" / "opportunities.db"


# --------------------------------------------------------------------- safety

@pytest.fixture(autouse=True)
def _never_call_real_claude(monkeypatch):
    """No test may shell out to the real `claude` binary, ever.

    `from claude_cli import run_claude` (etc.) copies a reference into the
    importing module's namespace, so patching `claude_cli.run_claude` alone
    would not stop `advisor.run_claude` from still pointing at the real
    thing. Every module that imported one of these names by hand is patched
    individually instead.
    """

    def _forbidden(*_args, **_kwargs):
        raise RuntimeError(
            "A test attempted to invoke the real claude CLI. Monkeypatch the "
            "specific entry point used by the code under test instead."
        )

    for module in (claude_cli, classifier, advisor, source_discovery, walten, main):
        if hasattr(module, "run_claude"):
            monkeypatch.setattr(module, "run_claude", _forbidden, raising=False)
        if hasattr(module, "run_claude_json"):
            monkeypatch.setattr(module, "run_claude_json", _forbidden, raising=False)
        if hasattr(module, "claude_available"):
            monkeypatch.setattr(module, "claude_available", lambda *a, **kw: False, raising=False)
        if hasattr(module, "claude_version"):
            monkeypatch.setattr(module, "claude_version", lambda *a, **kw: None, raising=False)


@pytest.fixture(autouse=True)
def _forbid_real_db(monkeypatch):
    """Belt-and-suspenders: fail loudly if anything ever points at the real DB."""
    real_connect = database._connect

    def _guarded_connect():
        if database.DB_PATH.resolve() == REAL_DB_PATH.resolve():
            raise RuntimeError(
                f"Refusing to open the real database at {REAL_DB_PATH}. "
                "A test forgot to use the db_path/app_client fixture."
            )
        return real_connect()

    monkeypatch.setattr(database, "_connect", _guarded_connect)


# ------------------------------------------------------------------- database

@pytest.fixture
def db_path(tmp_path, monkeypatch) -> Path:
    """Point every `database.get_db()` call at a brand-new temp sqlite file."""
    path = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", path)
    database.init_db()
    # Rate limiting and listing verification would otherwise add real delay /
    # extra HTTP round trips to scraper tests; keep them deterministic.
    database.set_setting("domain_delay_seconds", "0")
    return path


@pytest.fixture
def app_client(db_path) -> Iterator[TestClient]:
    """A TestClient whose app lifespan runs against the temp database."""
    with TestClient(main.app) as client:
        yield client


# --------------------------------------------------------------------- walten

@pytest.fixture
def walten_tmp(tmp_path, monkeypatch) -> Path:
    """Redirect Walten's checkpoint repo and artifact dirs into a temp tree.

    Required by any test that calls walten.checkpoint/restore/ensure_repo,
    directly or via the API (sending a message, approving a plan, undoing).
    """
    project = tmp_path / "walten-project"
    (project / "backend").mkdir(parents=True)
    (project / "frontend").mkdir(parents=True)
    (project / "data").mkdir(parents=True)
    # `ensure_repo()`'s baseline commit is `git add -A && git commit`, with the
    # commit's exit code unchecked. On a genuinely empty tree that commit fails
    # (nothing to commit) and the repo is left with no HEAD at all — see the
    # documented bug in test_walten_checkpoints.py. A real project always has
    # trackable files, so give the fixture one too, matching real usage.
    (project / "README.md").write_text("test project placeholder\n")

    monkeypatch.setattr(walten, "PROJECT_ROOT", project)
    monkeypatch.setattr(walten, "CHECKPOINT_DIR", project / "data" / "checkpoints.git")
    monkeypatch.setattr(walten, "ARTIFACTS_DIR", project / "data" / "walten-artifacts")
    monkeypatch.setattr(walten, "CONTEXT_DIR", project / "data" / "walten-context")
    return project


# --------------------------------------------------------------- local http server

class _Routes:
    """Mutable table of canned responses a test can populate on the fly."""

    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, str, bytes]] = {}

    def set(self, path: str, *, status: int = 200, body: str = "", content_type: str = "text/html") -> None:
        self.routes[path] = (status, content_type, body.encode("utf-8"))


def _handler_factory(routes: _Routes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib naming
            entry = routes.routes.get(self.path)
            if entry is None:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"no route registered for this path")
                return
            status, content_type, body = entry
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass  # keep test output quiet

    return Handler


@pytest.fixture
def local_server() -> Iterator[tuple[str, _Routes]]:
    """A real HTTP server on 127.0.0.1 whose responses a test controls directly.

    Stands in for a job board so `scraper.py`'s fetch path can be exercised
    without ever reaching a real site.
    """
    routes = _Routes()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_factory(routes))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        yield base_url, routes
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
