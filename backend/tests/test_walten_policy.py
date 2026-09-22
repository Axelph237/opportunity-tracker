"""build_policy(mode, phase) for every combination.

Covers: Assist mode cannot write to backend/** or frontend/**; subagent tools
are denied in every combination; plan phase denies Write/Edit everywhere;
history-destroying git commands are always denied.
"""

from __future__ import annotations

import pytest

import walten

MODES = ("assistant", "engineer")
PHASES = ("plan", "apply")

# Tools that could delegate work, run arbitrary shells, or escape the project.
SUBAGENT_AND_DANGEROUS_TOOLS = [
    "Task", "Agent", "Workflow", "SendMessage", "ListAgents", "TaskStop",
    "Skill", "ToolSearch", "EnterWorktree", "ExitWorktree",
    "Bash(rm:*)", "Bash(sudo:*)", "Bash(curl:*)", "Bash(eval:*)",
]

HISTORY_DESTROYING_GIT_COMMANDS = [
    "Bash(git reset:*)", "Bash(git checkout:*)", "Bash(git restore:*)",
    "Bash(git rebase:*)", "Bash(git filter-branch:*)", "Bash(git push:*)",
    "Bash(git clean:*)", "Bash(git stash:*)", "Bash(git branch:*)",
    "Bash(git reflog expire:*)", "Bash(git gc:*)", "Bash(git prune:*)",
    "Bash(git read-tree:*)", "Bash(git update-ref:*)",
    # `git config core.hooksPath` would arrange for a script to run on the
    # next automatic commit — execution that does not look like execution.
    "Bash(git config:*)",
]


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("phase", PHASES)
def test_subagent_and_dangerous_tools_always_denied(mode, phase):
    policy = walten.build_policy(mode, phase)
    deny = policy["permissions"]["deny"]
    for tool in SUBAGENT_AND_DANGEROUS_TOOLS:
        assert tool in deny, f"{tool} should be denied for ({mode}, {phase})"


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("phase", PHASES)
def test_history_destroying_git_commands_always_denied(mode, phase):
    policy = walten.build_policy(mode, phase)
    deny = policy["permissions"]["deny"]
    for command in HISTORY_DESTROYING_GIT_COMMANDS:
        assert command in deny, f"{command} should be denied for ({mode}, {phase})"


@pytest.mark.parametrize("mode", MODES)
def test_plan_phase_denies_write_and_edit(mode):
    policy = walten.build_policy(mode, "plan")
    deny = policy["permissions"]["deny"]
    allow = policy["permissions"]["allow"]
    assert "Write" in deny
    assert "Edit" in deny
    assert "MultiEdit" in deny
    assert "Write" not in allow
    assert "Edit" not in allow


@pytest.mark.parametrize("mode", MODES)
def test_plan_phase_denies_db_writes(mode):
    policy = walten.build_policy(mode, "plan")
    deny = policy["permissions"]["deny"]
    for command in walten.DB_WRITE_COMMANDS:
        assert command in deny


def test_assist_apply_cannot_write_backend_or_frontend():
    policy = walten.build_policy("assistant", "apply")
    deny = policy["permissions"]["deny"]
    allow = policy["permissions"]["allow"]
    assert "Write(backend/**)" in deny
    assert "Edit(backend/**)" in deny
    assert "Write(frontend/**)" in deny
    assert "Edit(frontend/**)" in deny
    assert "Write(scripts/**)" in deny
    assert "Edit(scripts/**)" in deny
    assert "Write(.env)" in deny
    assert "Edit(.env)" in deny
    # Assist mode never gets the bare Write/Edit tools at all in apply phase.
    assert "Write" not in allow
    assert "Edit" not in allow


def test_assist_apply_can_run_its_own_scripts_and_write_artifacts():
    policy = walten.build_policy("assistant", "apply")
    allow = policy["permissions"]["allow"]
    for script in walten.ASSISTANT_SCRIPTS:
        assert script in allow
    assert any(rule.startswith("Write(data/walten-artifacts") for rule in allow)
    assert any(rule.startswith("Edit(data/walten-artifacts") for rule in allow)


def test_engineer_apply_can_write_and_use_git():
    policy = walten.build_policy("engineer", "apply")
    allow = policy["permissions"]["allow"]
    deny = policy["permissions"]["deny"]
    assert "Write" in allow
    assert "Edit" in allow
    assert "MultiEdit" in allow
    assert "Bash(git:*)" in allow
    # But the history-destroying git subcommands are still carved back out by deny.
    for command in HISTORY_DESTROYING_GIT_COMMANDS:
        assert command in deny


def test_engineer_apply_reenables_python_command():
    """DENY_SHELLS blocks Bash(python:*) generally; engineer mode carves it back out."""
    policy = walten.build_policy("engineer", "apply")
    deny = policy["permissions"]["deny"]
    allow = policy["permissions"]["allow"]
    assert "Bash(python:*)" not in deny
    assert "Bash(.venv/bin/python:*)" in allow


def test_assistant_apply_still_denies_shells():
    policy = walten.build_policy("assistant", "apply")
    deny = policy["permissions"]["deny"]
    assert "Bash(python:*)" in deny
    assert "Bash(python3:*)" in deny
    assert "Bash(rm:*)" in deny


def test_read_tools_and_db_read_always_allowed():
    for mode in MODES:
        for phase in PHASES:
            policy = walten.build_policy(mode, phase)
            allow = policy["permissions"]["allow"]
            for tool in walten.READ_TOOLS:
                assert tool in allow
            for command in walten.DB_READ_COMMANDS:
                assert command in allow


def test_engineer_plan_has_no_write_tools_even_though_engineer_apply_does():
    plan_policy = walten.build_policy("engineer", "plan")
    apply_policy = walten.build_policy("engineer", "apply")
    assert "Write" not in plan_policy["permissions"]["allow"]
    assert "Write" in apply_policy["permissions"]["allow"]
