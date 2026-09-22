"""Walten's git-backed checkpoint/undo mechanism, against a temp project root.

Every test here uses `walten_tmp`, which points walten.PROJECT_ROOT and
walten.CHECKPOINT_DIR (plus ARTIFACTS_DIR/CONTEXT_DIR) at a throwaway
directory, so nothing ever touches the real project's .git or working tree.
"""

from __future__ import annotations

import walten


def test_ensure_repo_on_a_truly_empty_tree_reports_failure(tmp_path, monkeypatch, db_path):
    """A baseline that could not be committed must be reported, not swallowed.

    `ensure_repo()` seeds the checkpoint repo with `git add -A && git commit`.
    With nothing trackable that commit fails and the repo is left with no HEAD,
    so every later checkpoint would resolve to None — an undo arrow offering a
    restore that cannot run. It returns a warning instead of claiming success.

    This cannot arise in the real app (backend/ and frontend/ always hold real
    files by the time the agent runs); the condition is recreated directly.
    """
    project = tmp_path / "genuinely-empty-project"
    (project / "backend").mkdir(parents=True)
    (project / "data").mkdir(parents=True)
    monkeypatch.setattr(walten, "PROJECT_ROOT", project)
    monkeypatch.setattr(walten, "CHECKPOINT_DIR", project / "data" / "checkpoints.git")

    warning = walten.ensure_repo()
    assert warning is not None
    assert "undo" in warning

    # And the caller is told, rather than handed an empty restore point.
    mark = walten.checkpoint("first message ever sent")
    assert mark["warning"] is not None
    assert mark["commit"] is None


def test_ensure_repo_succeeds_once_there_is_something_to_track(tmp_path, monkeypatch, db_path):
    """The same tree, with one real file in it, produces a usable baseline."""
    project = tmp_path / "normal-project"
    (project / "backend").mkdir(parents=True)
    (project / "data").mkdir(parents=True)
    (project / "backend" / "main.py").write_text("x = 1\n")
    monkeypatch.setattr(walten, "PROJECT_ROOT", project)
    monkeypatch.setattr(walten, "CHECKPOINT_DIR", project / "data" / "checkpoints.git")

    assert walten.ensure_repo() is None
    mark = walten.checkpoint("first message ever sent")
    assert mark["warning"] is None
    assert mark["commit"] and mark["tree"]
def test_ensure_repo_creates_bare_checkpoint_repo(walten_tmp, db_path):
    assert not walten.has_repo()
    warning = walten.ensure_repo()
    assert warning is None
    assert walten.has_repo()
    assert (walten_tmp / "data" / "checkpoints.git").is_dir()


def test_checkpoint_creates_a_restore_point(walten_tmp, db_path):
    (walten_tmp / "backend" / "app.py").write_text("print('v1')\n")
    mark = walten.checkpoint("first checkpoint")
    assert mark["warning"] is None
    assert mark["commit"]
    assert mark["tree"]


def test_checkpoint_with_nothing_changed_still_returns_current_tree(walten_tmp, db_path):
    (walten_tmp / "backend" / "app.py").write_text("print('v1')\n")
    first = walten.checkpoint("first")
    second = walten.checkpoint("second, nothing changed")
    assert second["tree"] == first["tree"]


def test_changes_since_reports_modified_file(walten_tmp, db_path):
    target = walten_tmp / "backend" / "app.py"
    target.write_text("print('v1')\n")
    before = walten.checkpoint("before edit")

    target.write_text("print('v2')\n")

    changed = walten.changes_since(before["tree"])
    assert "backend/app.py" in changed


def test_changes_since_reports_new_untracked_file(walten_tmp, db_path):
    before = walten.checkpoint("empty baseline")
    (walten_tmp / "backend" / "new_file.py").write_text("print('new')\n")

    changed = walten.changes_since(before["tree"])
    assert "backend/new_file.py" in changed


def test_changes_since_unknown_tree_returns_empty():
    # No repo at all yet: has_repo() is False, so changes_since must not blow up.
    assert walten.changes_since("deadbeef" * 5) == []


def test_changes_since_none_tree_returns_empty(walten_tmp, db_path):
    walten.checkpoint("baseline")
    assert walten.changes_since(None) == []


def test_restore_puts_file_back_without_rewriting_history(walten_tmp, db_path):
    target = walten_tmp / "backend" / "app.py"
    target.write_text("print('v1')\n")
    before = walten.checkpoint("v1 committed")

    target.write_text("print('v2')\n")
    walten.checkpoint("v2 committed")
    assert target.read_text() == "print('v2')\n"

    log_before = walten._git("log", "--oneline").stdout.strip().splitlines()

    result = walten.restore(before["tree"], "undo to v1")
    assert result["ok"] is True
    assert "backend/app.py" in result["changed"]
    assert target.read_text() == "print('v1')\n"

    # Undo is itself a new commit stacked on top; nothing earlier is gone.
    log_after = walten._git("log", "--oneline").stdout.strip().splitlines()
    assert len(log_after) > len(log_before)
    for old_line in log_before:
        assert old_line in log_after


def test_restore_removes_files_added_after_the_checkpoint(walten_tmp, db_path):
    before = walten.checkpoint("baseline, no extra files")
    extra = walten_tmp / "backend" / "temp_debug.py"
    extra.write_text("print('oops')\n")
    walten.checkpoint("added a debug file")

    result = walten.restore(before["tree"], "undo the debug file")
    assert result["ok"] is True
    assert not extra.exists()


def test_restore_is_a_noop_when_nothing_changed(walten_tmp, db_path):
    (walten_tmp / "backend" / "app.py").write_text("print('v1')\n")
    mark = walten.checkpoint("v1")

    result = walten.restore(mark["tree"], "no-op undo")
    assert result["ok"] is True
    assert result["changed"] == []


def test_restore_without_a_tree_is_refused(walten_tmp, db_path):
    walten.checkpoint("baseline")
    result = walten.restore(None, "nothing to restore")
    assert result["ok"] is False
    assert "no restore point" in result["error"].lower()


def test_restore_unreachable_tree_is_refused(walten_tmp, db_path):
    walten.checkpoint("baseline")
    result = walten.restore("deadbeef" * 5, "bogus tree")
    assert result["ok"] is False
    assert "no longer in the repository" in result["error"]


def test_working_state_reports_dirty_when_uncommitted_changes_exist(walten_tmp, db_path):
    walten.checkpoint("baseline")
    assert walten.working_state()["dirty"] is False

    (walten_tmp / "backend" / "app.py").write_text("uncommitted\n")
    assert walten.working_state()["dirty"] is True


def test_working_state_without_a_repo_is_not_ok(walten_tmp, db_path):
    state = walten.working_state()
    assert state == {"ok": False, "tree": None, "dirty": False}


def test_checkpoint_excludes_data_directory(walten_tmp, db_path):
    """The checkpoint repo must not track data/ (that's where the real DB lives)."""
    (walten_tmp / "data" / "opportunities.db").write_bytes(b"not a real db")
    walten.checkpoint("baseline")
    tracked = walten._git("ls-files").stdout.splitlines()
    assert "data/opportunities.db" not in tracked
