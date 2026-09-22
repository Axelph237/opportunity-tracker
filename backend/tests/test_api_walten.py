"""fastapi.testclient coverage for /api/walten: sessions, messages, checkpoints/undo.

Every test that sends a message, approves a plan, or undoes one needs
`walten_tmp` (redirects the checkpoint git repo into a temp dir) in addition
to `app_client` (fresh temp database). The two are independent fixtures and
can be requested together.
"""

from __future__ import annotations

import database
import walten


def test_walten_overview(app_client):
    resp = app_client.get("/api/walten")
    assert resp.status_code == 200
    body = resp.json()
    assert body["claude_cli"] is False  # guarded by the suite-wide claude stub
    assert body["sessions"] == []
    assert "name" in body and "icon" in body


def test_create_and_get_session(app_client):
    created = app_client.post("/api/walten/sessions", json={"mode": "assistant", "model": "sonnet"})
    assert created.status_code == 201
    body = created.json()
    assert body["title"] == "New session"
    assert body["mode"] == "assistant"
    assert body["messages"] == []
    assert body["running"] is False

    fetched = app_client.get(f"/api/walten/sessions/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


def test_get_session_404(app_client):
    resp = app_client.get("/api/walten/sessions/999")
    assert resp.status_code == 404


def test_update_session(app_client):
    session = app_client.post("/api/walten/sessions", json={}).json()
    resp = app_client.patch(
        f"/api/walten/sessions/{session['id']}",
        json={"title": "Renamed", "mode": "engineer", "context_urls": ["https://example.com/doc"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Renamed"
    assert body["mode"] == "engineer"
    assert body["context_urls"] == ["https://example.com/doc"]


def test_update_session_404(app_client):
    resp = app_client.patch("/api/walten/sessions/999", json={"title": "x"})
    assert resp.status_code == 404


def test_delete_session(app_client):
    session = app_client.post("/api/walten/sessions", json={}).json()
    resp = app_client.delete(f"/api/walten/sessions/{session['id']}")
    assert resp.status_code == 204
    assert app_client.get(f"/api/walten/sessions/{session['id']}").status_code == 404


def test_delete_session_404(app_client):
    resp = app_client.delete("/api/walten/sessions/999")
    assert resp.status_code == 404


# ------------------------------------------------------------------ sending messages

def test_send_message_creates_checkpoint_and_records_error_without_claude(app_client, walten_tmp):
    session = app_client.post("/api/walten/sessions", json={"mode": "assistant"}).json()

    resp = app_client.post(f"/api/walten/sessions/{session['id']}/messages", json={"prompt": "Tidy up my sources"})
    assert resp.status_code == 200
    # The endpoint builds its response body *before* the background task that
    # runs the actual turn is executed by Starlette, so the immediate response
    # only ever contains the user message; the assistant's reply lands after.
    immediate_body = resp.json()
    assert len(immediate_body["messages"]) == 1
    user_message = immediate_body["messages"][0]
    assert user_message["role"] == "user"
    assert user_message["snapshot_sha"]  # a real checkpoint commit was taken
    # The session was named after the first line of the prompt.
    assert immediate_body["title"] == "Tidy up my sources"

    # By the time the TestClient call returns, Starlette has already awaited
    # the background task (run_turn), so a follow-up GET sees the recorded
    # assistant turn too.
    follow_up = app_client.get(f"/api/walten/sessions/{session['id']}")
    body = follow_up.json()
    assert len(body["messages"]) == 2
    assistant_message = body["messages"][1]
    assert assistant_message["role"] == "assistant"
    # No claude CLI in the test environment (by design) -> the turn records an error.
    assert assistant_message["error"] is not None
    assert "ClaudeUnavailable" in assistant_message["error"]


def test_send_message_while_running_is_409(app_client, walten_tmp):
    session = app_client.post("/api/walten/sessions", json={}).json()
    session_id = session["id"]

    walten.RUNNING[session_id] = walten.TurnState(session_id=session_id, phase="plan")
    try:
        resp = app_client.post(f"/api/walten/sessions/{session_id}/messages", json={"prompt": "hello"})
        assert resp.status_code == 409
    finally:
        walten.RUNNING.pop(session_id, None)


def test_send_message_empty_prompt_is_422(app_client):
    session = app_client.post("/api/walten/sessions", json={}).json()
    resp = app_client.post(f"/api/walten/sessions/{session['id']}/messages", json={"prompt": ""})
    assert resp.status_code == 422


# ------------------------------------------------------------------- approve/reject

def test_approve_with_nothing_pending_is_409(app_client, walten_tmp):
    session = app_client.post("/api/walten/sessions", json={}).json()
    resp = app_client.post(f"/api/walten/sessions/{session['id']}/approve")
    assert resp.status_code == 409


def test_approve_resolves_pending_plan_and_snapshots_in_engineer_mode(app_client, walten_tmp, db_path):
    session = app_client.post("/api/walten/sessions", json={"mode": "engineer"}).json()
    session_id = session["id"]

    with database.get_db() as conn:
        conn.execute(
            "INSERT INTO walten_messages (session_id, role, phase, content, needs_approval, resolved) "
            "VALUES (?, 'assistant', 'plan', 'Here is my plan.', 1, 0)",
            (session_id,),
        )
        pending_id = conn.execute(
            "SELECT id FROM walten_messages WHERE session_id = ? AND needs_approval = 1", (session_id,)
        ).fetchone()["id"]

    resp = app_client.post(f"/api/walten/sessions/{session_id}/approve")
    assert resp.status_code == 200

    with database.get_db() as conn:
        resolved = conn.execute(
            "SELECT resolved FROM walten_messages WHERE id = ?", (pending_id,)
        ).fetchone()["resolved"]
    assert resolved == 1
    # engineer mode approval takes a snapshot; the checkpoint repo must now exist.
    assert walten.has_repo()


def test_reject_resolves_pending_plan_without_running_a_turn(app_client, db_path):
    session = app_client.post("/api/walten/sessions", json={}).json()
    session_id = session["id"]

    with database.get_db() as conn:
        conn.execute(
            "INSERT INTO walten_messages (session_id, role, phase, content, needs_approval, resolved) "
            "VALUES (?, 'assistant', 'plan', 'Here is my plan.', 1, 0)",
            (session_id,),
        )

    resp = app_client.post(f"/api/walten/sessions/{session_id}/reject")
    assert resp.status_code == 200
    body = resp.json()
    # No new assistant turn was recorded by rejecting.
    assert len(body["messages"]) == 1


# ------------------------------------------------------------------------- undo

def test_undo_preview_before_any_checkpoint_message_errors(app_client, db_path):
    session = app_client.post("/api/walten/sessions", json={}).json()
    with database.get_db() as conn:
        conn.execute(
            "INSERT INTO walten_messages (session_id, role, phase, content) VALUES (?, 'user', 'plan', 'hi')",
            (session["id"],),
        )
        message_id = conn.execute("SELECT id FROM walten_messages WHERE session_id = ?", (session["id"],)).fetchone()["id"]

    resp = app_client.get(f"/api/walten/sessions/{session['id']}/messages/{message_id}/undo")
    assert resp.status_code == 200
    body = resp.json()
    assert body["can_undo"] is False
    assert body["error"] is not None


def test_undo_message_404_for_wrong_session_or_role(app_client, db_path):
    session = app_client.post("/api/walten/sessions", json={}).json()
    resp = app_client.get(f"/api/walten/sessions/{session['id']}/messages/999/undo")
    assert resp.status_code == 404


def test_undo_preview_and_execute_restores_file(app_client, walten_tmp):
    session = app_client.post("/api/walten/sessions", json={"mode": "engineer"}).json()
    session_id = session["id"]

    # Establish a baseline file before the checkpoint-bearing message is sent.
    target = walten_tmp / "backend" / "app.py"
    target.write_text("print('before')\n")

    sent = app_client.post(
        f"/api/walten/sessions/{session_id}/messages", json={"prompt": "Change app.py"}
    ).json()
    user_message = sent["messages"][0]

    # Simulate the agent having changed a file after the checkpoint was taken.
    target.write_text("print('after')\n")

    preview = app_client.get(f"/api/walten/sessions/{session_id}/messages/{user_message['id']}/undo")
    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["can_undo"] is True
    assert "backend/app.py" in preview_body["files"]

    undo = app_client.post(f"/api/walten/sessions/{session_id}/messages/{user_message['id']}/undo")
    assert undo.status_code == 200
    undo_body = undo.json()
    assert undo_body["ok"] is True
    assert "backend/app.py" in undo_body["files"]
    assert target.read_text() == "print('before')\n"


def test_undo_refused_while_turn_is_running(app_client, walten_tmp):
    session = app_client.post("/api/walten/sessions", json={"mode": "engineer"}).json()
    session_id = session["id"]

    sent = app_client.post(
        f"/api/walten/sessions/{session_id}/messages", json={"prompt": "Do something"}
    ).json()
    user_message = sent["messages"][0]

    walten.RUNNING[session_id] = walten.TurnState(session_id=session_id, phase="apply")
    try:
        resp = app_client.post(f"/api/walten/sessions/{session_id}/messages/{user_message['id']}/undo")
        assert resp.status_code == 409
        assert "running turn" in resp.json()["detail"].lower()
    finally:
        walten.RUNNING.pop(session_id, None)


# -------------------------------------------------------------------- stop / context

def test_stop_turn_when_nothing_running(app_client):
    session = app_client.post("/api/walten/sessions", json={}).json()
    resp = app_client.post(f"/api/walten/sessions/{session['id']}/stop")
    assert resp.status_code == 200


def test_upload_context_file(app_client, walten_tmp):
    session = app_client.post("/api/walten/sessions", json={}).json()
    resp = app_client.post(
        f"/api/walten/sessions/{session['id']}/context",
        files={"file": ("notes.txt", b"some attached context", "text/plain")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert any(f.endswith("notes.txt") for f in body["context_files"])
    stored = walten_tmp / "data" / "walten-context" / str(session["id"]) / "notes.txt"
    assert stored.read_bytes() == b"some attached context"


def test_upload_context_file_empty_is_400(app_client, walten_tmp):
    session = app_client.post("/api/walten/sessions", json={}).json()
    resp = app_client.post(
        f"/api/walten/sessions/{session['id']}/context",
        files={"file": ("notes.txt", b"", "text/plain")},
    )
    assert resp.status_code == 400
