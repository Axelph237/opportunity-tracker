"""walten_db.py: the audited, SELECT-only database CLI handed to the agent.

Calls the module's command functions directly (no subprocess) against the
per-test temp database.
"""

from __future__ import annotations

import argparse

import pytest

import database
import walten_db


def _query_ns(sql: str, limit: int = 200) -> argparse.Namespace:
    return argparse.Namespace(sql=sql, limit=limit)


def test_cmd_query_runs_a_plain_select(db_path, capsys):
    walten_db.cmd_query(_query_ns("SELECT id, name FROM sources LIMIT 1"))
    out = capsys.readouterr().out
    assert '"name"' in out


def test_cmd_query_rejects_multiple_statements(db_path):
    with pytest.raises(SystemExit):
        walten_db.cmd_query(_query_ns("SELECT 1; SELECT 2"))


def test_cmd_query_rejects_non_select(db_path):
    with pytest.raises(SystemExit):
        walten_db.cmd_query(_query_ns("DELETE FROM sources"))


def test_cmd_query_rejects_semicolon_smuggled_statement(db_path):
    with pytest.raises(SystemExit):
        walten_db.cmd_query(_query_ns("SELECT * FROM sources; DROP TABLE sources"))


def test_cmd_query_rejects_update_disguised_with_select_prefix(db_path):
    with pytest.raises(SystemExit):
        walten_db.cmd_query(_query_ns("SELECT 1 FROM (UPDATE sources SET name = 'x')"))


def test_cmd_query_rejects_pragma_table_valued_function(db_path):
    """Regression test: `pragma\\w*` must catch `pragma_table_info(...)` too.

    A bare `pragma\\b` word-boundary regex does not match here because `_` is
    a word character, so "pragma" and "_table_info" never have a boundary
    between them — the table-valued pragma functions slipped straight past
    the old pattern. This asserts the fix (walten_db.py's FORBIDDEN_RE) holds.
    """
    with pytest.raises(SystemExit):
        walten_db.cmd_query(_query_ns("SELECT * FROM pragma_table_info('sources')"))


def test_cmd_query_allows_cte_feeding_a_select(db_path):
    walten_db.cmd_query(_query_ns("WITH x AS (SELECT 1 AS n) SELECT n FROM x"))


def test_cmd_update_only_allows_writable_tables(db_path):
    ns = argparse.Namespace(table="settings", row_id=1, set=["value=x"])
    with pytest.raises(SystemExit):
        walten_db.cmd_update(ns)


def test_cmd_update_rejects_unknown_column(db_path):
    with database.get_db() as conn:
        conn.execute(
            "INSERT INTO opportunities (title, organization, type, url) VALUES ('T', 'O', 'job', 'https://x/1')"
        )
        row_id = conn.execute("SELECT id FROM opportunities").fetchone()["id"]

    ns = argparse.Namespace(table="opportunities", row_id=row_id, set=["not_a_real_column=x"])
    with pytest.raises(SystemExit):
        walten_db.cmd_update(ns)


def test_cmd_update_sets_column_on_writable_table(db_path, capsys):
    with database.get_db() as conn:
        conn.execute(
            "INSERT INTO opportunities (title, organization, type, url) VALUES ('T', 'O', 'job', 'https://x/1')"
        )
        row_id = conn.execute("SELECT id FROM opportunities").fetchone()["id"]

    walten_db.cmd_update(argparse.Namespace(table="opportunities", row_id=row_id, set=["notes=looks good"]))

    with database.get_db() as conn:
        notes = conn.execute("SELECT notes FROM opportunities WHERE id = ?", (row_id,)).fetchone()["notes"]
    assert notes == "looks good"


def test_cmd_update_null_literal_sets_column_to_none(db_path):
    with database.get_db() as conn:
        conn.execute(
            "INSERT INTO opportunities (title, organization, type, url, notes) VALUES ('T', 'O', 'job', 'https://x/1', 'x')"
        )
        row_id = conn.execute("SELECT id FROM opportunities").fetchone()["id"]

    walten_db.cmd_update(argparse.Namespace(table="opportunities", row_id=row_id, set=["notes=null"]))

    with database.get_db() as conn:
        notes = conn.execute("SELECT notes FROM opportunities WHERE id = ?", (row_id,)).fetchone()["notes"]
    assert notes is None


def test_cmd_delete_only_allows_writable_tables(db_path):
    with pytest.raises(SystemExit):
        walten_db.cmd_delete(argparse.Namespace(table="scrape_logs", row_id=1))


def test_cmd_delete_removes_row(db_path, capsys):
    with database.get_db() as conn:
        conn.execute(
            "INSERT INTO opportunities (title, organization, type, url) VALUES ('T', 'O', 'job', 'https://x/1')"
        )
        row_id = conn.execute("SELECT id FROM opportunities").fetchone()["id"]

    walten_db.cmd_delete(argparse.Namespace(table="opportunities", row_id=row_id))

    with database.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) c FROM opportunities WHERE id = ?", (row_id,)).fetchone()["c"] == 0


def test_cmd_schema_prints_readable_tables(db_path, capsys):
    walten_db.cmd_schema(argparse.Namespace())
    out = capsys.readouterr().out
    assert "CREATE TABLE" in out
    assert "sources" in out
