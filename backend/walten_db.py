"""Audited database CLI for the in-app agent.

The agent is not given raw `sqlite3` or unrestricted Python. It goes through this
script, which makes reads obviously safe (SELECT only) and makes every write
narrow, logged and refusable.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

from database import get_db

# Only these tables can be written through this CLI. Schema and settings tables
# are readable but never writable from here.
WRITABLE_TABLES = {"opportunities", "applications", "sources", "excluded_urls"}
READABLE_TABLES = WRITABLE_TABLES | {
    "source_proposals",
    "scrape_logs",
    "resume_advice",
    "role_analyses",
    "settings",
    "walten_sessions",
    "walten_messages",
}

# A statement is only run if it is a single SELECT (or a CTE feeding one).
SELECT_RE = re.compile(r"^\s*(with\b.*?\bselect\b|select\b)", re.IGNORECASE | re.DOTALL)
FORBIDDEN_RE = re.compile(
    # `pragma\w*` not `pragma\b`: an underscore is a word character, so a
    # word boundary never matches between "pragma" and "_table_info",
    # and the table-valued `pragma_*()` functions slipped straight past.
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma\w*|vacuum)\b",
    re.IGNORECASE,
)


def _fail(message: str) -> None:
    print(f"REFUSED: {message}", file=sys.stderr)
    raise SystemExit(2)


def cmd_schema(_: argparse.Namespace) -> None:
    with get_db() as conn:
        for table in sorted(READABLE_TABLES):
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if row and row["sql"]:
                print(row["sql"].strip(), ";\n", sep="")


def cmd_query(args: argparse.Namespace) -> None:
    sql = args.sql.strip().rstrip(";")
    if ";" in sql:
        _fail("one statement at a time")
    if not SELECT_RE.match(sql):
        _fail("only SELECT statements are allowed here")
    if FORBIDDEN_RE.search(re.sub(r"'[^']*'", "''", sql)):
        _fail("that statement writes; use the update or delete command instead")

    with get_db() as conn:
        rows = conn.execute(f"SELECT * FROM ({sql}) LIMIT {int(args.limit)}").fetchall()
    payload = [dict(row) for row in rows]
    print(json.dumps(payload, indent=2, default=str))
    print(f"\n{len(payload)} row(s)", file=sys.stderr)


def _parse_set(pairs: list[str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            _fail(f"--set expects column=value, got {pair!r}")
        column, raw = pair.split("=", 1)
        column = column.strip()
        if not column.isidentifier():
            _fail(f"invalid column name {column!r}")
        values[column] = None if raw == "null" else raw
    return values


def cmd_update(args: argparse.Namespace) -> None:
    if args.table not in WRITABLE_TABLES:
        _fail(f"{args.table} is not writable; allowed: {', '.join(sorted(WRITABLE_TABLES))}")
    values = _parse_set(args.set or [])
    if not values:
        _fail("nothing to set")

    assignments = ", ".join(f"{column} = ?" for column in values)
    with get_db() as conn:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({args.table})")}
        unknown = set(values) - columns
        if unknown:
            _fail(f"unknown column(s): {', '.join(sorted(unknown))}")
        cur = conn.execute(
            f"UPDATE {args.table} SET {assignments} WHERE id = ?", [*values.values(), args.row_id]
        )
    print(f"updated {cur.rowcount} row(s) in {args.table} (id={args.row_id})")


def cmd_delete(args: argparse.Namespace) -> None:
    if args.table not in WRITABLE_TABLES:
        _fail(f"{args.table} is not writable")
    with get_db() as conn:
        cur = conn.execute(f"DELETE FROM {args.table} WHERE id = ?", (args.row_id,))
    print(f"deleted {cur.rowcount} row(s) from {args.table} (id={args.row_id})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("schema", help="print the schema of every readable table").set_defaults(func=cmd_schema)

    query = sub.add_parser("query", help="run one SELECT and print JSON rows")
    query.add_argument("sql")
    query.add_argument("--limit", type=int, default=200)
    query.set_defaults(func=cmd_query)

    update = sub.add_parser("update", help="set columns on one row by id")
    update.add_argument("table")
    update.add_argument("row_id", type=int)
    update.add_argument("--set", action="append", metavar="COL=VALUE")
    update.set_defaults(func=cmd_update)

    remove = sub.add_parser("delete", help="delete one row by id")
    remove.add_argument("table")
    remove.add_argument("row_id", type=int)
    remove.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
