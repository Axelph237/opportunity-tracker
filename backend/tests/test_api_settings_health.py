"""fastapi.testclient coverage for /api/health, /api/stats and /api/settings."""

from __future__ import annotations

import database


def test_health_endpoint(app_client):
    resp = app_client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "counts" in body
    assert set(body["counts"]) == {"sources", "opportunities", "applications", "source_proposals"}


def test_stats_endpoint(app_client):
    resp = app_client.get("/api/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert "opportunities" in body
    assert "walten_name" in body
    assert body["onboarding_complete"] is False


def test_get_settings(app_client):
    resp = app_client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert "settings" in body
    assert "cron_schedule" in body
    assert body["claude_cli"] is False  # guarded by the test-suite-wide stub


def test_update_settings_happy_path(app_client):
    resp = app_client.patch("/api/settings", json={"model": "opus", "onboarding_complete": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["settings"]["model"] == "opus"
    assert body["settings"]["onboarding_complete"] == "1"


def test_update_settings_unknown_key_is_silently_ignored(app_client):
    """`update_settings` has a dead `400 Unknown settings` branch.

    `MUTABLE_SETTINGS` (main.py) lists exactly the fields declared on the
    `SettingsUpdate` pydantic model (models.py), and a plain `BaseModel`
    drops unrecognised JSON keys during validation (extra="ignore" is the
    v2 default) rather than passing them through. So `set(data) -
    MUTABLE_SETTINGS` can never be non-empty via this endpoint, and the 400
    it would raise is unreachable in practice. Documenting the actual
    (harmless) behaviour here rather than the intended one; not fixed per
    instructions.
    """
    resp = app_client.patch("/api/settings", json={"not_a_real_setting": "x"})
    assert resp.status_code == 200


def test_update_settings_invalid_cron_is_400(app_client):
    resp = app_client.patch("/api/settings", json={"cron_schedule": "not a cron"})
    assert resp.status_code == 400


def test_update_settings_valid_cron_applies(app_client):
    resp = app_client.patch("/api/settings", json={"cron_schedule": "0 9 * * *"})
    assert resp.status_code == 200
    assert resp.json()["cron_schedule"] == "0 9 * * *"


def test_check_claude_path_rejects_nonexistent_binary(app_client):
    resp = app_client.post("/api/settings/claude-path", json={"path": "/definitely/not/a/real/binary"})
    assert resp.status_code == 400


def test_check_claude_path_empty_clears_override(app_client, db_path):
    database.set_setting("claude_bin", "/some/old/path")
    resp = app_client.post("/api/settings/claude-path", json={"path": ""})
    assert resp.status_code == 200
    assert database.get_setting("claude_bin") == ""


def test_resume_status_endpoint(app_client):
    resp = app_client.get("/api/settings/resume")
    assert resp.status_code == 200
    body = resp.json()
    assert "loaded" in body
    assert "characters" in body


def test_upload_resume_rejects_empty_file(app_client):
    resp = app_client.post(
        "/api/settings/resume",
        files={"file": ("resume.txt", b"", "text/plain")},
    )
    assert resp.status_code == 400


def test_upload_resume_rejects_unsupported_format(app_client, tmp_path):
    resp = app_client.post(
        "/api/settings/resume",
        files={"file": ("resume.docx", b"hello world", "application/msword")},
    )
    assert resp.status_code == 400


def test_scrape_status_endpoint(app_client):
    resp = app_client.get("/api/scrape/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "running" in body
    assert "cron_schedule" in body


def test_scrape_log_tail_endpoint(app_client):
    resp = app_client.get("/api/scrape/log-tail")
    assert resp.status_code == 200
    body = resp.json()
    assert body["running"] is False
    assert body["lines"] == []


def test_scrape_run_now_and_conflict(app_client, db_path, monkeypatch):
    import scheduler as scheduler_module

    # Avoid an actual scrape (which would hit the network / claude); just
    # prove the endpoint starts a background task and rejects a second one
    # while a scrape is "running".
    async def _fake_run(self, source_ids=None):
        return {}

    monkeypatch.setattr(scheduler_module.ScrapeRunner, "run", _fake_run)

    resp = app_client.post("/api/scrape/run-now")
    assert resp.status_code == 200
    assert resp.json()["started"] is True

    scheduler_module.runner.running = True
    try:
        conflict = app_client.post("/api/scrape/run-now")
        assert conflict.status_code == 409
    finally:
        scheduler_module.runner.running = False


def test_scrape_source_404(app_client):
    resp = app_client.post("/api/scrape/source/999")
    assert resp.status_code == 404


def test_scrape_logs_endpoint_empty(app_client):
    resp = app_client.get("/api/scrape/logs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_scrape_logs_endpoint_with_rows(app_client, db_path):
    with database.get_db() as conn:
        conn.execute(
            "INSERT INTO sources (name, url, type) VALUES ('S', 'https://s.example', 'job_board')"
        )
        source_id = conn.execute("SELECT id FROM sources WHERE url='https://s.example'").fetchone()["id"]
        conn.execute(
            "INSERT INTO scrape_logs (source_id, status, new_count, error_message) VALUES (?, 'success', 3, NULL)",
            (source_id,),
        )
        conn.execute(
            "INSERT INTO scrape_logs (source_id, status, new_count, error_message) VALUES (?, 'error', 0, 'boom')",
            (source_id,),
        )

    all_logs = app_client.get("/api/scrape/logs").json()
    assert len(all_logs) == 2

    only_errors = app_client.get("/api/scrape/logs", params={"status": "error"}).json()
    assert len(only_errors) == 1 and only_errors[0]["error_message"] == "boom"
