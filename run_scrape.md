# Task: Run the twice-daily opportunity scrape

You are running headlessly from cron in the Opportunity Tracker project root.
Work autonomously and do not ask questions — there is no one to answer them.

## Context

- The scraper and classifier are plain Python modules with no Anthropic API
  dependency. `backend/classifier.py` shells back out to `claude -p` for the
  actual scoring, so no API key is involved anywhere.
- The Python virtualenv lives at `.venv/`. Always use `.venv/bin/python`.
- All state lives in the SQLite database at `data/opportunities.db`.

## Steps

1. Run the scrape and capture the machine-readable summary:

   ```bash
   .venv/bin/python backend/scraper.py --json
   ```

   This fetches every active source, extracts listing chunks, scores each new
   listing against the resume, and writes new rows to `opportunities`. It
   deduplicates by URL, so re-running is safe and cheap.

2. Read the JSON summary. For every entry in `detail` with
   `"status": "error"`, note the source name and the error message.

3. Inspect the strongest new matches so the report is useful:

   ```bash
   .venv/bin/python - <<'PY'
   import sqlite3
   conn = sqlite3.connect("data/opportunities.db")
   conn.row_factory = sqlite3.Row
   rows = conn.execute("""
       SELECT o.title, o.organization, o.relevance_score, o.deadline, o.url, s.name AS source
       FROM opportunities o LEFT JOIN sources s ON s.id = o.source_id
       WHERE o.date_found >= datetime('now', '-1 day')
       ORDER BY o.relevance_score DESC LIMIT 15
   """).fetchall()
   for r in rows:
       print(f"{r['relevance_score']:>4}  {r['title'][:60]:<60} {r['organization'][:28]:<28} {r['deadline'] or '-'}")
       print(f"      {r['url']}")
   PY
   ```

4. Disable only sources that are persistently dead. A single 404 is usually a
   moved page, not a removed one, so require three consecutive 404 runs before
   deactivating anything:

   ```bash
   .venv/bin/python - <<'PY'
   import sqlite3
   conn = sqlite3.connect("data/opportunities.db")
   conn.row_factory = sqlite3.Row
   dead = []
   for source in conn.execute("SELECT id, name FROM sources WHERE active = 1"):
       recent = conn.execute(
           "SELECT status, error_message FROM scrape_logs WHERE source_id = ? ORDER BY timestamp DESC LIMIT 3",
           (source["id"],),
       ).fetchall()
       if len(recent) == 3 and all(
           row["status"] == "error" and "404" in (row["error_message"] or "") for row in recent
       ):
           dead.append(source)
   for source in dead:
       conn.execute(
           "UPDATE sources SET active = 0, notes = COALESCE(notes || ' | ', '') || 'auto-disabled: 404 x3' "
           "WHERE id = ?",
           (source["id"],),
       )
   conn.commit()
   print("disabled:", ", ".join(s["name"] for s in dead) or "none")
   PY
   ```

   Never auto-disable on 403 or timeout — those are bot-blocking or transient,
   and the page is usually still live.

5. Print a short final report, in this shape and nothing more:

   ```
   SCRAPE REPORT <ISO timestamp>
   sources: <n> scraped, <n> errors
   new opportunities: <n>
   top matches:
     <score>  <title> — <organization> (<deadline>)
     ...
   failures:
     <source name>: <error>
     ...
   disabled this run: <source names, or "none">
   ```

## Rules

- Never edit source code during a cron run — only run the scraper and update
  the database rows described above.
- Never delete rows from `opportunities`, `applications` or `sources`.
- If `.venv/bin/python` is missing, print `SCRAPE REPORT: venv missing` and stop.
