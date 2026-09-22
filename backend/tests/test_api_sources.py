"""fastapi.testclient coverage for /api/sources, plus the sources status feature.

The scrape-triggered half of the status feature (blocked/error/success actually
being set by scraper.scrape_source) is covered in test_scraper_network.py; this
file covers the API's own rule about *clearing* that flag on edit.
"""

from __future__ import annotations

import database


def _seed_source(conn, **overrides) -> int:
    values = {
        "name": "Test Source",
        "url": "https://src.example/jobs",
        "type": "job_board",
        "scrape_method": "html",
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    conn.execute(f"INSERT INTO sources ({columns}) VALUES ({placeholders})", list(values.values()))
    return conn.execute("SELECT id FROM sources WHERE url = ?", (values["url"],)).fetchone()["id"]


def test_create_source_happy_path(app_client):
    resp = app_client.post(
        "/api/sources",
        json={"name": "New Board", "url": "https://board.example/jobs", "type": "job_board"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "New Board"
    assert body["active"] is True
    assert body["pending_approval"] is False


def test_create_source_invalid_type_is_422(app_client):
    resp = app_client.post(
        "/api/sources",
        json={"name": "Bad", "url": "https://bad.example", "type": "not-a-real-type"},
    )
    assert resp.status_code == 422


def test_create_source_duplicate_url_is_409(app_client, db_path):
    with database.get_db() as conn:
        _seed_source(conn)
    resp = app_client.post(
        "/api/sources",
        json={"name": "Duplicate", "url": "https://src.example/jobs", "type": "job_board"},
    )
    assert resp.status_code == 409


def test_list_sources_excludes_pending_by_default(app_client, db_path):
    with database.get_db() as conn:
        _seed_source(conn, url="https://a.example", pending_approval=1)
        _seed_source(conn, url="https://b.example", pending_approval=0)

    default = app_client.get("/api/sources").json()
    assert all(not s["pending_approval"] for s in default)
    assert not any(s["url"] == "https://a.example" for s in default)
    assert any(s["url"] == "https://b.example" for s in default)

    including_pending = app_client.get("/api/sources", params={"include_pending": True}).json()
    assert any(s["url"] == "https://a.example" for s in including_pending)
    assert any(s["url"] == "https://b.example" for s in including_pending)


def test_update_source_404(app_client):
    resp = app_client.patch("/api/sources/999", json={"name": "x"})
    assert resp.status_code == 404


def test_update_source_duplicate_url_is_409(app_client, db_path):
    with database.get_db() as conn:
        _seed_source(conn, url="https://a.example")
        other_id = _seed_source(conn, url="https://b.example")

    resp = app_client.patch(f"/api/sources/{other_id}", json={"url": "https://a.example"})
    assert resp.status_code == 409


def test_delete_source_404(app_client):
    resp = app_client.delete("/api/sources/999")
    assert resp.status_code == 404


def test_delete_source(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn)
    resp = app_client.delete(f"/api/sources/{source_id}")
    assert resp.status_code == 204
    assert app_client.patch(f"/api/sources/{source_id}", json={"name": "y"}).status_code == 404


# ------------------------------------------------------------- status clearing

def test_editing_url_clears_blocked_status(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn)
        conn.execute(
            "UPDATE sources SET last_status = 'blocked', last_error = 'HTTP 403' WHERE id = ?",
            (source_id,),
        )

    resp = app_client.patch(f"/api/sources/{source_id}", json={"url": "https://src.example/new-jobs"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_status"] is None
    assert body["last_error"] is None


def test_editing_scrape_method_clears_error_status(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn)
        conn.execute(
            "UPDATE sources SET last_status = 'error', last_error = 'HTTP 500' WHERE id = ?",
            (source_id,),
        )

    resp = app_client.patch(f"/api/sources/{source_id}", json={"scrape_method": "api"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_status"] is None
    assert body["last_error"] is None


def test_editing_search_query_clears_status(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn, scrape_method="search_query")
        conn.execute(
            "UPDATE sources SET last_status = 'blocked', last_error = 'HTTP 429' WHERE id = ?",
            (source_id,),
        )

    resp = app_client.patch(f"/api/sources/{source_id}", json={"search_query": "quantum computing"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_status"] is None
    assert body["last_error"] is None


def test_editing_name_does_not_clear_status(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn)
        conn.execute(
            "UPDATE sources SET last_status = 'blocked', last_error = 'HTTP 403' WHERE id = ?",
            (source_id,),
        )

    resp = app_client.patch(f"/api/sources/{source_id}", json={"name": "Renamed Source"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Renamed Source"
    assert body["last_status"] == "blocked"
    assert body["last_error"] == "HTTP 403"


def test_editing_notes_does_not_clear_status(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn)
        conn.execute(
            "UPDATE sources SET last_status = 'error', last_error = 'HTTP 500' WHERE id = ?",
            (source_id,),
        )

    resp = app_client.patch(f"/api/sources/{source_id}", json={"notes": "investigate later"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["notes"] == "investigate later"
    assert body["last_status"] == "error"
    assert body["last_error"] == "HTTP 500"


def test_setting_url_to_same_value_does_not_clear_status(app_client, db_path):
    """Only an actual change to url/scrape_method/search_query clears the flag."""
    with database.get_db() as conn:
        source_id = _seed_source(conn)
        conn.execute(
            "UPDATE sources SET last_status = 'blocked', last_error = 'HTTP 403' WHERE id = ?",
            (source_id,),
        )

    resp = app_client.patch(f"/api/sources/{source_id}", json={"url": "https://src.example/jobs"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["last_status"] == "blocked"
    assert body["last_error"] == "HTTP 403"


# ------------------------------------------------------------------- proposals

def test_approve_proposal_creates_source(app_client, db_path):
    with database.get_db() as conn:
        conn.execute(
            """INSERT INTO source_proposals (name, url, type, scrape_method, rationale, confidence, status)
               VALUES ('New Board', 'https://newboard.example', 'job_board', 'html', 'good fit', 0.9, 'pending')"""
        )
        proposal_id = conn.execute("SELECT id FROM source_proposals").fetchone()["id"]

    resp = app_client.post(f"/api/sources/proposals/{proposal_id}/approve")
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"] == "https://newboard.example"
    assert body["added_by"] == "claude"

    already = app_client.post(f"/api/sources/proposals/{proposal_id}/approve")
    assert already.status_code == 409


def test_approve_proposal_404(app_client):
    resp = app_client.post("/api/sources/proposals/999/approve")
    assert resp.status_code == 404


def test_reject_proposal(app_client, db_path):
    with database.get_db() as conn:
        conn.execute(
            """INSERT INTO source_proposals (name, url, type, scrape_method, status)
               VALUES ('Skip Me', 'https://skip.example', 'job_board', 'html', 'pending')"""
        )
        proposal_id = conn.execute("SELECT id FROM source_proposals").fetchone()["id"]

    resp = app_client.post(f"/api/sources/proposals/{proposal_id}/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


def test_reject_proposal_404(app_client):
    resp = app_client.post("/api/sources/proposals/999/reject")
    assert resp.status_code == 404


def test_discover_sources_endpoint_uses_mocked_claude(app_client, db_path, monkeypatch):
    import source_discovery

    def _fake_run_claude(*_args, **_kwargs):
        import json

        return json.dumps(
            [
                {
                    "name": "Fake Lab Careers",
                    "url": "https://fakelab.example/careers",
                    "type": "government",
                    "scrape_method": "html",
                    "rationale": "matches quantum focus",
                    "confidence": 0.8,
                }
            ]
        )

    monkeypatch.setattr(source_discovery, "run_claude", _fake_run_claude)

    resp = app_client.post("/api/sources/discover", json={"count": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["name"] == "Fake Lab Careers"
    assert body[0]["status"] == "pending"


def test_discover_sources_502_on_claude_call_error(app_client, db_path, monkeypatch):
    import source_discovery

    def _boom(*_args, **_kwargs):
        raise source_discovery.ClaudeCallError("network issue")

    monkeypatch.setattr(source_discovery, "run_claude", _boom)

    resp = app_client.post("/api/sources/discover", json={"count": 1})
    assert resp.status_code == 502
