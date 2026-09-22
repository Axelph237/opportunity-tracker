"""fastapi.testclient coverage for /api/applications."""

from __future__ import annotations

import database


def _seed_opportunity(conn, **overrides) -> int:
    values = {
        "title": "Quantum Intern",
        "organization": "IonQ",
        "type": "internship",
        "url": "https://src.example/jobs/1",
        "relevance_score": 8.2,
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    conn.execute(f"INSERT INTO opportunities ({columns}) VALUES ({placeholders})", list(values.values()))
    return conn.execute("SELECT id FROM opportunities WHERE url = ?", (values["url"],)).fetchone()["id"]


def test_create_application_happy_path(app_client, db_path):
    with database.get_db() as conn:
        opp_id = _seed_opportunity(conn)

    resp = app_client.post("/api/applications", json={"opportunity_id": opp_id, "status": "bookmarked"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["opportunity_id"] == opp_id
    assert body["status"] == "bookmarked"
    assert body["opportunity"]["id"] == opp_id


def test_create_application_404_for_missing_opportunity(app_client):
    resp = app_client.post("/api/applications", json={"opportunity_id": 999})
    assert resp.status_code == 404


def test_create_application_409_when_already_tracked(app_client, db_path):
    with database.get_db() as conn:
        opp_id = _seed_opportunity(conn)

    first = app_client.post("/api/applications", json={"opportunity_id": opp_id})
    assert first.status_code == 201
    second = app_client.post("/api/applications", json={"opportunity_id": opp_id})
    assert second.status_code == 409


def test_create_application_invalid_status_is_422(app_client, db_path):
    with database.get_db() as conn:
        opp_id = _seed_opportunity(conn)

    resp = app_client.post("/api/applications", json={"opportunity_id": opp_id, "status": "not-a-status"})
    assert resp.status_code == 422


def test_update_application_sets_date_applied_on_status_flip(app_client, db_path):
    with database.get_db() as conn:
        opp_id = _seed_opportunity(conn)
    created = app_client.post("/api/applications", json={"opportunity_id": opp_id}).json()
    assert created["date_applied"] is None

    resp = app_client.patch(f"/api/applications/{created['id']}", json={"status": "applied"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "applied"
    assert body["date_applied"] is not None


def test_update_application_contacts_roundtrip(app_client, db_path):
    with database.get_db() as conn:
        opp_id = _seed_opportunity(conn)
    created = app_client.post("/api/applications", json={"opportunity_id": opp_id}).json()

    contacts = [{"name": "Jane Doe", "role": "Recruiter", "email": "jane@example.com"}]
    resp = app_client.patch(f"/api/applications/{created['id']}", json={"contacts": contacts})
    assert resp.status_code == 200
    assert resp.json()["contacts"][0]["name"] == "Jane Doe"


def test_update_application_404(app_client):
    resp = app_client.patch("/api/applications/999", json={"status": "applied"})
    assert resp.status_code == 404


def test_delete_application(app_client, db_path):
    with database.get_db() as conn:
        opp_id = _seed_opportunity(conn)
    created = app_client.post("/api/applications", json={"opportunity_id": opp_id}).json()

    resp = app_client.delete(f"/api/applications/{created['id']}")
    assert resp.status_code == 204
    assert app_client.patch(f"/api/applications/{created['id']}", json={"notes": "x"}).status_code == 404


def test_delete_application_404(app_client):
    resp = app_client.delete("/api/applications/999")
    assert resp.status_code == 404


def test_list_applications_filters_and_search(app_client, db_path):
    with database.get_db() as conn:
        opp1 = _seed_opportunity(conn, url="https://src.example/jobs/1", title="Quantum Intern", type="internship")
        opp2 = _seed_opportunity(conn, url="https://src.example/jobs/2", title="Backend Engineer", type="job")
    app_client.post("/api/applications", json={"opportunity_id": opp1, "status": "bookmarked"})
    app_client.post("/api/applications", json={"opportunity_id": opp2, "status": "applied"})

    all_apps = app_client.get("/api/applications").json()
    assert len(all_apps) == 2

    only_applied = app_client.get("/api/applications", params={"status": "applied"}).json()
    assert len(only_applied) == 1 and only_applied[0]["opportunity"]["title"] == "Backend Engineer"

    searched = app_client.get("/api/applications", params={"search": "Quantum"}).json()
    assert len(searched) == 1 and searched[0]["opportunity"]["title"] == "Quantum Intern"


def test_application_statuses_endpoint(app_client):
    resp = app_client.get("/api/applications/statuses")
    assert resp.status_code == 200
    statuses = resp.json()
    assert "bookmarked" in statuses and "applied" in statuses and "rejected" in statuses
