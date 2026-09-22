"""fastapi.testclient coverage for /api/insights/roles (the aggregate role landscape)."""

from __future__ import annotations

import json

import database


def _seed_opportunity(conn, **overrides) -> int:
    values = {
        "title": "Quantum Intern",
        "organization": "IonQ",
        "type": "internship",
        "url": "https://src.example/jobs/1",
        "relevance_score": 8.2,
        "is_active": 1,
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    conn.execute(f"INSERT INTO opportunities ({columns}) VALUES ({placeholders})", list(values.values()))
    return conn.execute("SELECT id FROM opportunities WHERE url = ?", (values["url"],)).fetchone()["id"]


FAKE_LANDSCAPE = {
    "summary": "A cluster of quantum hardware and software roles.",
    "role_groups": [
        {"label": "Quantum software", "count": 1, "description": "writes control software", "example_titles": ["Quantum Intern"]}
    ],
    "requirements": [
        {"requirement": "Python", "frequency": "most roles", "status": "met", "evidence": "resume shows Python", "gap_note": None}
    ],
    "recommended_skills": [
        {"skill": "Qiskit", "why": "widely used", "unlocks": "hardware roles", "effort": "a weekend", "priority": "high"}
    ],
    "strengths": ["Strong Python background"],
}


def test_get_role_analysis_null_when_none_generated(app_client):
    resp = app_client.get("/api/insights/roles")
    assert resp.status_code == 200
    assert resp.json() is None


def test_create_role_analysis_happy_path(app_client, db_path, monkeypatch):
    import advisor

    with database.get_db() as conn:
        _seed_opportunity(conn)

    monkeypatch.setattr(advisor, "run_claude", lambda *a, **kw: json.dumps(FAKE_LANDSCAPE))
    monkeypatch.setattr(advisor, "get_resume_text", lambda: "Experienced Python developer.")

    resp = app_client.post("/api/insights/roles", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] == FAKE_LANDSCAPE["summary"]
    assert body["role_groups"][0]["label"] == "Quantum software"
    assert body["opportunity_count"] == 1

    # And it is now retrievable as "latest".
    latest = app_client.get("/api/insights/roles")
    assert latest.status_code == 200
    assert latest.json()["id"] == body["id"]


def test_create_role_analysis_no_opportunities_is_502(app_client, db_path, monkeypatch):
    import advisor

    monkeypatch.setattr(advisor, "get_resume_text", lambda: "Some resume text.")
    resp = app_client.post("/api/insights/roles", json={})
    assert resp.status_code == 502


def test_create_role_analysis_no_resume_is_502(app_client, db_path, monkeypatch):
    import advisor

    with database.get_db() as conn:
        _seed_opportunity(conn)

    monkeypatch.setattr(advisor, "get_resume_text", lambda: None)
    resp = app_client.post("/api/insights/roles", json={})
    assert resp.status_code == 502


def test_create_role_analysis_filters_by_type(app_client, db_path, monkeypatch):
    import advisor

    with database.get_db() as conn:
        _seed_opportunity(conn, url="https://a.example/1", type="internship")
        _seed_opportunity(conn, url="https://a.example/2", type="job")

    captured = {}

    def _fake_run_claude(prompt, **kwargs):
        captured["prompt"] = prompt
        return json.dumps(FAKE_LANDSCAPE)

    monkeypatch.setattr(advisor, "run_claude", _fake_run_claude)
    monkeypatch.setattr(advisor, "get_resume_text", lambda: "resume text")

    resp = app_client.post("/api/insights/roles", json={"type": ["internship"]})
    assert resp.status_code == 200
    assert resp.json()["opportunity_count"] == 1
    assert "job" not in captured["prompt"] or "internship" in captured["prompt"]


def test_update_role_analysis_stamps_edited_at(app_client, db_path, monkeypatch):
    import advisor

    with database.get_db() as conn:
        _seed_opportunity(conn)

    monkeypatch.setattr(advisor, "run_claude", lambda *a, **kw: json.dumps(FAKE_LANDSCAPE))
    monkeypatch.setattr(advisor, "get_resume_text", lambda: "resume text")
    created = app_client.post("/api/insights/roles", json={}).json()
    assert created["edited_at"] is None

    resp = app_client.patch(f"/api/insights/roles/{created['id']}", json={"summary": "Hand-edited summary."})
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] == "Hand-edited summary."
    assert body["edited_at"] is not None


def test_update_role_analysis_404(app_client):
    resp = app_client.patch("/api/insights/roles/999", json={"summary": "x"})
    assert resp.status_code == 404


def test_role_analysis_history(app_client, db_path, monkeypatch):
    import advisor

    with database.get_db() as conn:
        _seed_opportunity(conn)

    monkeypatch.setattr(advisor, "run_claude", lambda *a, **kw: json.dumps(FAKE_LANDSCAPE))
    monkeypatch.setattr(advisor, "get_resume_text", lambda: "resume text")
    app_client.post("/api/insights/roles", json={})
    app_client.post("/api/insights/roles", json={})

    resp = app_client.get("/api/insights/roles/history")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
