"""fastapi.testclient coverage for /api/job-posts.

Fetching is exercised against the `local_server` fixture, never the real web:
the blocked-domain behaviour this has to pin down is a property of our code,
and asserting it against a third-party job board would make the suite depend on
that board's mood.
"""

from __future__ import annotations

import json

import pytest

import database
import jobposts
from claude_cli import ClaudeCallError, ClaudeUnavailable

FAKE_KEYWORDS = {
    "keywords": [
        {"term": "Qiskit", "bucket": "technical", "weight": 0.9, "variants": ["qiskit-terra"]},
        {"term": "characterize", "bucket": "verb", "weight": 0.6, "variants": ["characterized"]},
        {"term": "collaboration", "bucket": "professional", "weight": 0.4, "variants": []},
    ]
}

AD = (
    "We are hiring a quantum software intern to characterize superconducting qubits. "
    "You will write Qiskit pulse schedules, analyse readout fidelity and present results "
    "to the hardware team. Strong collaboration skills required. "
) * 6

# Long on purpose. A short refusal would be caught by the thin-body guard, so
# only a denial page bulky enough to look like real content proves the status
# check is what keeps it out of raw_text.
DENIAL_PAGE = (
    "<html><body><main><h1>Access Denied</h1>"
    + "<p>You do not have permission to access this resource on this server. "
    "Your request has been blocked by our security policy. Reference number 18004412. "
    "If you believe this is an error, contact the site administrator. </p>" * 4
    + "</main></body></html>"
)


def _create(client, **overrides) -> dict:
    payload = {"title": "Quantum Intern", "raw_text": AD}
    payload.update(overrides)
    response = client.post("/api/job-posts", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _seed_opportunity(conn, url: str = "https://src.example/jobs/1") -> int:
    conn.execute(
        "INSERT INTO opportunities (title, organization, type, url) VALUES ('Intern', 'IonQ', 'internship', ?)",
        (url,),
    )
    return conn.execute("SELECT id FROM opportunities WHERE url = ?", (url,)).fetchone()["id"]


def test_a_pasted_advertisement_is_stored_verbatim_as_the_posts_raw_text(app_client):
    post = _create(app_client)

    assert post["raw_text"] == AD
    assert post["source"] == "pasted"
    assert post["keywords"] == []
    assert post["extracted_at"] is None


def test_a_job_post_can_exist_without_being_linked_to_a_scraped_listing(app_client):
    post = _create(app_client)

    assert post["opportunity_id"] is None
    assert app_client.get(f"/api/job-posts/{post['id']}").json()["opportunity_id"] is None


def test_a_job_post_can_be_linked_to_a_scraped_listing(app_client, db_path):
    with database.get_db() as conn:
        opportunity_id = _seed_opportunity(conn)

    post = _create(app_client, opportunity_id=opportunity_id)
    assert post["opportunity_id"] == opportunity_id


def test_two_job_posts_cannot_claim_the_same_listing(app_client, db_path):
    with database.get_db() as conn:
        opportunity_id = _seed_opportunity(conn)

    _create(app_client, opportunity_id=opportunity_id)
    clash = app_client.post(
        "/api/job-posts",
        json={"title": "Duplicate", "raw_text": AD, "opportunity_id": opportunity_id},
    )

    assert clash.status_code == 409
    assert len(app_client.get("/api/job-posts").json()) == 1


def test_several_job_posts_may_each_have_no_listing(app_client):
    """The unique index on opportunity_id is partial; NULL must not collide."""
    _create(app_client, title="One")
    _create(app_client, title="Two")

    assert len(app_client.get("/api/job-posts").json()) == 2


def test_fetching_a_job_post_that_does_not_exist_is_a_404(app_client):
    assert app_client.get("/api/job-posts/999").status_code == 404


def test_patching_a_job_post_replaces_only_the_fields_sent(app_client):
    post = _create(app_client)

    response = app_client.patch(f"/api/job-posts/{post['id']}", json={"organization": "ACME"})

    assert response.status_code == 200
    body = response.json()
    assert body["organization"] == "ACME"
    assert body["title"] == "Quantum Intern"
    assert body["raw_text"] == AD


def test_patching_a_job_post_that_does_not_exist_is_a_404(app_client):
    assert app_client.patch("/api/job-posts/999", json={"organization": "ACME"}).status_code == 404


def test_a_deleted_job_post_is_gone_from_the_list(app_client):
    post = _create(app_client)

    assert app_client.delete(f"/api/job-posts/{post['id']}").status_code == 204
    assert app_client.get("/api/job-posts").json() == []
    assert app_client.delete(f"/api/job-posts/{post['id']}").status_code == 404


def test_extracting_keywords_stores_all_three_buckets_against_the_post(app_client, monkeypatch):
    monkeypatch.setattr(jobposts, "run_claude", lambda *a, **kw: json.dumps(FAKE_KEYWORDS))
    post = _create(app_client)

    response = app_client.post(f"/api/job-posts/{post['id']}/keywords")

    assert response.status_code == 200
    body = response.json()
    assert [kw["term"] for kw in body["keywords"]] == ["Qiskit", "characterize", "collaboration"]
    assert [kw["bucket"] for kw in body["keywords"]] == ["technical", "verb", "professional"]
    assert body["keywords"][0]["variants"] == ["qiskit-terra"]
    assert body["extracted_at"] is not None


def test_a_second_keyword_request_serves_the_cache_and_refresh_runs_the_model_again(app_client, monkeypatch):
    calls = []

    def _fake_run_claude(prompt, **kwargs):
        calls.append(prompt)
        return json.dumps(FAKE_KEYWORDS)

    monkeypatch.setattr(jobposts, "run_claude", _fake_run_claude)
    post = _create(app_client)

    app_client.post(f"/api/job-posts/{post['id']}/keywords")
    app_client.post(f"/api/job-posts/{post['id']}/keywords")
    assert len(calls) == 1

    app_client.post(f"/api/job-posts/{post['id']}/keywords?refresh=true")
    assert len(calls) == 2


def test_the_advertisement_text_is_what_the_model_is_asked_about(app_client, monkeypatch):
    captured = {}

    def _fake_run_claude(prompt, **kwargs):
        captured["prompt"] = prompt
        return json.dumps(FAKE_KEYWORDS)

    monkeypatch.setattr(jobposts, "run_claude", _fake_run_claude)
    post = _create(app_client, organization="IonQ")

    app_client.post(f"/api/job-posts/{post['id']}/keywords")

    assert "superconducting qubits" in captured["prompt"]
    assert "IonQ" in captured["prompt"]


def test_a_garbage_model_response_normalizes_to_a_usable_list_rather_than_failing(app_client, monkeypatch):
    garbage = {
        "keywords": [
            None,
            42,
            "not an object",
            {"bucket": "technical"},
            {"term": "   "},
            {"term": "Qiskit", "bucket": "wat", "weight": "very high", "variants": "qiskit-terra"},
            {"term": "qiskit", "bucket": "verb", "weight": 0.1},
            {"term": "Rust", "weight": 99, "variants": [None, "", "rustlang", "rustlang"]},
        ]
    }
    monkeypatch.setattr(jobposts, "run_claude", lambda *a, **kw: json.dumps(garbage))
    post = _create(app_client)

    response = app_client.post(f"/api/job-posts/{post['id']}/keywords")

    assert response.status_code == 200
    keywords = response.json()["keywords"]
    assert [kw["term"] for kw in keywords] == ["Qiskit", "Rust"]
    assert keywords[0]["bucket"] == "technical"
    assert keywords[0]["weight"] == 1.0
    assert keywords[0]["variants"] == ["qiskit-terra"]
    assert keywords[1]["weight"] == 1.0
    assert keywords[1]["variants"] == ["rustlang"]


def test_a_response_that_is_not_json_at_all_is_a_502_rather_than_a_crash(app_client, monkeypatch):
    monkeypatch.setattr(jobposts, "run_claude", lambda *a, **kw: "I cannot help with that.")
    post = _create(app_client)

    assert app_client.post(f"/api/job-posts/{post['id']}/keywords").status_code == 502


def test_a_response_with_no_usable_keywords_is_retried_rather_than_cached(app_client, monkeypatch):
    calls = []

    def _fake_run_claude(prompt, **kwargs):
        calls.append(prompt)
        return json.dumps({"keywords": []})

    monkeypatch.setattr(jobposts, "run_claude", _fake_run_claude)
    post = _create(app_client)

    assert app_client.post(f"/api/job-posts/{post['id']}/keywords").json()["keywords"] == []
    app_client.post(f"/api/job-posts/{post['id']}/keywords")

    assert len(calls) == 2


def test_a_failing_model_call_is_a_502(app_client, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise ClaudeCallError("claude exited with code 1")

    monkeypatch.setattr(jobposts, "run_claude", _boom)
    post = _create(app_client)

    assert app_client.post(f"/api/job-posts/{post['id']}/keywords").status_code == 502


def test_a_missing_claude_cli_is_a_503(app_client, monkeypatch):
    def _missing(*_args, **_kwargs):
        raise ClaudeUnavailable("`claude` was not found on PATH.")

    monkeypatch.setattr(jobposts, "run_claude", _missing)
    post = _create(app_client)

    assert app_client.post(f"/api/job-posts/{post['id']}/keywords").status_code == 503


def test_extracting_keywords_before_any_advertisement_text_exists_is_a_400(app_client, monkeypatch):
    monkeypatch.setattr(jobposts, "run_claude", lambda *a, **kw: json.dumps(FAKE_KEYWORDS))
    post = _create(app_client, raw_text="")

    assert app_client.post(f"/api/job-posts/{post['id']}/keywords").status_code == 400


def test_extracting_keywords_for_a_post_that_does_not_exist_is_a_404(app_client):
    assert app_client.post("/api/job-posts/999/keywords").status_code == 404


def test_fetching_pulls_the_advertisement_off_the_page_and_marks_the_post_fetched(app_client, local_server):
    base_url, routes = local_server
    routes.set("/job/1", body=f"<html><body><main><p>{AD}</p></main></body></html>")
    post = _create(app_client, raw_text="", url=f"{base_url}/job/1")

    response = app_client.post(f"/api/job-posts/{post['id']}/fetch")

    assert response.status_code == 200
    body = response.json()
    assert "superconducting qubits" in body["raw_text"]
    assert body["source"] == "fetched"


def test_a_blocked_page_is_a_502_and_leaves_the_pasted_text_untouched(app_client, local_server):
    base_url, routes = local_server
    routes.set("/blocked", status=403, body=DENIAL_PAGE)
    post = _create(app_client, url=f"{base_url}/blocked")

    response = app_client.post(f"/api/job-posts/{post['id']}/fetch")

    assert response.status_code == 502
    assert "403" in response.json()["detail"]
    assert "paste" in response.json()["detail"].lower()

    stored = app_client.get(f"/api/job-posts/{post['id']}").json()
    assert stored["raw_text"] == AD
    assert stored["source"] == "pasted"
    assert "Access Denied" not in stored["raw_text"]


def test_a_page_too_thin_to_be_an_advertisement_is_a_502_and_is_not_stored(app_client, local_server):
    base_url, routes = local_server
    routes.set("/shell", body="<html><body><div id='root'></div><p>Loading…</p></body></html>")
    post = _create(app_client, url=f"{base_url}/shell")

    response = app_client.post(f"/api/job-posts/{post['id']}/fetch")

    assert response.status_code == 502
    assert "paste" in response.json()["detail"].lower()
    assert app_client.get(f"/api/job-posts/{post['id']}").json()["raw_text"] == AD


def test_an_unreachable_host_is_a_502_and_is_not_stored(app_client):
    """Port 1 refuses immediately, so this needs no DNS and cannot hang."""
    post = _create(app_client, url="http://127.0.0.1:1/job/1")

    response = app_client.post(f"/api/job-posts/{post['id']}/fetch")

    assert response.status_code == 502
    assert app_client.get(f"/api/job-posts/{post['id']}").json()["raw_text"] == AD


def test_fetching_a_post_with_no_url_is_a_400(app_client):
    post = _create(app_client)

    assert app_client.post(f"/api/job-posts/{post['id']}/fetch").status_code == 400


def test_fetching_a_post_that_does_not_exist_is_a_404(app_client):
    assert app_client.post("/api/job-posts/999/fetch").status_code == 404
