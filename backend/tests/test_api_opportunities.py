"""fastapi.testclient coverage for /api/opportunities."""

from __future__ import annotations

import database


def _seed_source(conn) -> int:
    conn.execute(
        "INSERT INTO sources (name, url, type) VALUES ('Test Source', 'https://src.example/jobs', 'job_board')"
    )
    return conn.execute("SELECT id FROM sources WHERE url = 'https://src.example/jobs'").fetchone()["id"]


def _seed_opportunity(conn, source_id, **overrides):
    values = {
        "title": "Quantum Intern",
        "organization": "IonQ",
        "type": "internship",
        "location": "College Park, MD",
        "remote": 0,
        "url": "https://src.example/jobs/1",
        "description": "Do quantum things",
        "deadline": "2027-01-15",
        "source_id": source_id,
        "relevance_score": 8.2,
        "relevance_summary": "Great fit",
        "skill_matches": '["Python", "Qiskit"]',
        "experience_level": "student",
        "strong_match": 1,
        "tags": '["quantum"]',
        "is_active": 1,
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    conn.execute(f"INSERT INTO opportunities ({columns}) VALUES ({placeholders})", list(values.values()))
    return conn.execute("SELECT id FROM opportunities WHERE url = ?", (values["url"],)).fetchone()["id"]


def test_list_opportunities_empty(app_client):
    resp = app_client.get("/api/opportunities")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_and_get_opportunity_shape(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn)
        opp_id = _seed_opportunity(conn, source_id)

    resp = app_client.get("/api/opportunities")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    item = body[0]
    assert item["id"] == opp_id
    assert item["title"] == "Quantum Intern"
    assert item["skill_matches"] == ["Python", "Qiskit"]
    assert item["tags"] == ["quantum"]
    assert item["strong_match"] is True
    assert item["source_name"] == "Test Source"
    assert item["application_id"] is None

    detail = app_client.get(f"/api/opportunities/{opp_id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["id"] == opp_id
    assert detail_body["application"] is None


def test_get_opportunity_404(app_client):
    resp = app_client.get("/api/opportunities/999")
    assert resp.status_code == 404


def test_list_opportunities_filters(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn)
        _seed_opportunity(conn, source_id, url="https://src.example/jobs/1", type="internship", strong_match=1, relevance_score=9.0)
        _seed_opportunity(conn, source_id, url="https://src.example/jobs/2", type="job", strong_match=0, relevance_score=3.0, title="Backend Engineer")
        _seed_opportunity(conn, source_id, url="https://src.example/jobs/3", type="job", strong_match=0, relevance_score=1.0, is_active=0, title="Stale Listing")

    only_internships = app_client.get("/api/opportunities", params={"type": "internship"}).json()
    assert {o["type"] for o in only_internships} == {"internship"}

    strong_only = app_client.get("/api/opportunities", params={"strong_match": True}).json()
    assert len(strong_only) == 1 and strong_only[0]["strong_match"] is True

    inactive_hidden = app_client.get("/api/opportunities").json()
    assert all(o["title"] != "Stale Listing" for o in inactive_hidden)

    inactive_shown = app_client.get("/api/opportunities", params={"include_inactive": True}).json()
    assert any(o["title"] == "Stale Listing" for o in inactive_shown)

    searched = app_client.get("/api/opportunities", params={"search": "Backend"}).json()
    assert len(searched) == 1 and searched[0]["title"] == "Backend Engineer"

    min_score = app_client.get("/api/opportunities", params={"min_score": 5}).json()
    assert all(o["relevance_score"] >= 5 for o in min_score)


def test_update_opportunity_partial_edit(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn)
        opp_id = _seed_opportunity(conn, source_id)

    resp = app_client.patch(f"/api/opportunities/{opp_id}", json={"notes": "applied via referral"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["notes"] == "applied via referral"
    # Untouched fields survive.
    assert body["title"] == "Quantum Intern"


def test_update_opportunity_blanks_optional_field(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn)
        opp_id = _seed_opportunity(conn, source_id)

    resp = app_client.patch(f"/api/opportunities/{opp_id}", json={"location": ""})
    assert resp.status_code == 200
    assert resp.json()["location"] is None


def test_update_opportunity_recomputes_strong_match(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn)
        opp_id = _seed_opportunity(conn, source_id, relevance_score=3.0, strong_match=0)

    resp = app_client.patch(f"/api/opportunities/{opp_id}", json={"relevance_score": 8.0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["relevance_score"] == 8.0
    assert body["strong_match"] is True


def test_update_opportunity_404(app_client):
    resp = app_client.patch("/api/opportunities/999", json={"notes": "x"})
    assert resp.status_code == 404


def test_update_opportunity_empty_title_is_422(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn)
        opp_id = _seed_opportunity(conn, source_id)

    resp = app_client.patch(f"/api/opportunities/{opp_id}", json={"title": "   "})
    assert resp.status_code == 422


def test_update_opportunity_duplicate_url_is_409(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn)
        _seed_opportunity(conn, source_id, url="https://src.example/jobs/1")
        opp2 = _seed_opportunity(conn, source_id, url="https://src.example/jobs/2")

    resp = app_client.patch(f"/api/opportunities/{opp2}", json={"url": "https://src.example/jobs/1"})
    assert resp.status_code == 409


def test_delete_opportunity_forgets_url_by_default(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn)
        opp_id = _seed_opportunity(conn, source_id)

    resp = app_client.delete(f"/api/opportunities/{opp_id}")
    assert resp.status_code == 204
    assert app_client.get(f"/api/opportunities/{opp_id}").status_code == 404
    assert "https://src.example/jobs/1" in database.excluded_urls()


def test_delete_opportunity_forget_false_does_not_exclude(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn)
        opp_id = _seed_opportunity(conn, source_id)

    resp = app_client.delete(f"/api/opportunities/{opp_id}", params={"forget": "false"})
    assert resp.status_code == 204
    assert "https://src.example/jobs/1" not in database.excluded_urls()


def test_delete_opportunity_404(app_client):
    resp = app_client.delete("/api/opportunities/999")
    assert resp.status_code == 404


def test_resume_advice_404_when_none_generated(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn)
        opp_id = _seed_opportunity(conn, source_id)

    resp = app_client.get(f"/api/opportunities/{opp_id}/resume-advice")
    assert resp.status_code == 404


def test_create_resume_advice_returns_cached_value(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn)
        opp_id = _seed_opportunity(conn, source_id)
        conn.execute(
            """INSERT INTO resume_advice (opportunity_id, fit_summary, fit_score, requirements, adjustments, keywords, talking_points)
               VALUES (?, 'Good fit', 7.0, '[]', '[]', '[]', '[]')""",
            (opp_id,),
        )

    resp = app_client.post(f"/api/opportunities/{opp_id}/resume-advice")
    assert resp.status_code == 200
    body = resp.json()
    assert body["fit_summary"] == "Good fit"
    assert body["stale"] is False


def test_create_resume_advice_502_when_claude_call_fails(app_client, db_path, monkeypatch):
    import advisor

    with database.get_db() as conn:
        source_id = _seed_source(conn)
        opp_id = _seed_opportunity(conn, source_id)

    def _boom(*_args, **_kwargs):
        raise advisor.ClaudeCallError("simulated failure")

    monkeypatch.setattr(advisor, "run_claude", _boom)

    resp = app_client.post(f"/api/opportunities/{opp_id}/resume-advice")
    assert resp.status_code == 502


def test_delete_resume_advice_404_when_missing(app_client, db_path):
    with database.get_db() as conn:
        source_id = _seed_source(conn)
        opp_id = _seed_opportunity(conn, source_id)

    resp = app_client.delete(f"/api/opportunities/{opp_id}/resume-advice")
    assert resp.status_code == 404
