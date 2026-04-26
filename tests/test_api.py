import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

INLINE_HELLO = {
    "workflow": {
        "name": "hello_inline",
        "nodes": [
            {
                "id": "t1",
                "type": "manual_trigger",
                "config": {"initial_data": {"u": "X"}},
            },
            {"id": "l1", "type": "log", "config": {"message": "Hi {input.u}"}},
        ],
        "edges": [{"from": "t1", "to": "l1"}],
    }
}

CYCLIC = {
    "workflow": {
        "name": "cyc",
        "nodes": [
            {"id": "a", "type": "log", "config": {"message": "x"}},
            {"id": "b", "type": "log", "config": {"message": "y"}},
        ],
        "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
    }
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def _wait_terminal(client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    last: dict = {}
    while time.monotonic() < deadline:
        last = client.get(f"/jobs/{job_id}").json()
        if last["status"] in {"success", "failed"}:
            return last
        time.sleep(0.05)
    pytest.fail(f"job {job_id} did not finish in {timeout}s; last={last}")


# ---------- meta ----------

def test_health(client: TestClient):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_api_docs_endpoints_disabled(client: TestClient):
    # Frontend (React Flow) — єдиний UI; авто-документація API повністю вимкнена.
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404


# ---------- /jobs/run + lifecycle ----------

def test_post_jobs_run_returns_pending_job(client: TestClient):
    r = client.post("/jobs/run", json=INLINE_HELLO)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "pending"
    assert "id" in body and body["workflow_name"] == "hello_inline"


def test_full_job_lifecycle_inline(client: TestClient):
    job_id = client.post("/jobs/run", json=INLINE_HELLO).json()["id"]
    body = _wait_terminal(client, job_id)
    assert body["status"] == "success", body
    assert body["error"] is None
    assert body["finished_at"] is not None
    assert "t1" in body["result"] and "l1" in body["result"]
    assert any(e["level"] == "done" for e in body["logs"])


def test_run_request_requires_one_of_two_fields(client: TestClient):
    r = client.post("/jobs/run", json={})
    assert r.status_code == 422
    r = client.post(
        "/jobs/run",
        json={"workflow_name": "x", "workflow": INLINE_HELLO["workflow"]},
    )
    assert r.status_code == 422


def test_cycle_returns_400_with_specific_message(client: TestClient):
    r = client.post("/jobs/run", json=CYCLIC)
    assert r.status_code == 400
    assert "cycle" in r.text.lower()
    assert "['a', 'b']" in r.text


def test_path_traversal_in_write_file_marks_job_failed(client: TestClient):
    payload = {
        "workflow": {
            "name": "evil",
            "nodes": [
                {
                    "id": "t1",
                    "type": "manual_trigger",
                    "config": {"initial_data": {"content": "evil"}},
                },
                {"id": "w1", "type": "write_file", "config": {"path": "../../etc/passwd"}},
            ],
            "edges": [{"from": "t1", "to": "w1"}],
        }
    }
    job_id = client.post("/jobs/run", json=payload).json()["id"]
    body = _wait_terminal(client, job_id)
    assert body["status"] == "failed"
    assert "outside sandbox" in (body["error"] or "")


def test_get_job_404_for_unknown(client: TestClient):
    r = client.get("/jobs/does-not-exist")
    assert r.status_code == 404


def test_list_jobs_returns_recent(client: TestClient):
    client.post("/jobs/run", json=INLINE_HELLO)
    r = client.get("/jobs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------- workflows CRUD ----------

def test_workflows_crud_round_trip(client: TestClient):
    workflow = {
        "name": "crud_test",
        "nodes": [{"id": "t1", "type": "manual_trigger", "config": {}}],
        "edges": [],
    }
    try:
        r = client.post("/workflows", json=workflow)
        assert r.status_code == 201, r.text

        r = client.get("/workflows")
        assert "crud_test" in r.json()

        r = client.get("/workflows/crud_test")
        assert r.status_code == 200
        assert r.json()["name"] == "crud_test"
    finally:
        client.delete("/workflows/crud_test")
    assert client.get("/workflows/crud_test").status_code == 404


def test_get_workflow_invalid_name_returns_400(client: TestClient):
    # `_safe_path` блокує імена з небезпечними символами; через path-параметр
    # відправляємо валідне URL-енкодоване ім'я з крапкою.
    r = client.get("/workflows/with.dot")
    assert r.status_code == 400


def test_delete_unknown_workflow_returns_404(client: TestClient):
    r = client.delete("/workflows/__never_existed__")
    assert r.status_code == 404


def test_run_saved_workflow_by_name(client: TestClient):
    workflow = INLINE_HELLO["workflow"] | {"name": "saved_hello"}
    try:
        r = client.post("/workflows", json=workflow)
        assert r.status_code == 201, r.text
        r = client.post("/jobs/run", json={"workflow_name": "saved_hello"})
        assert r.status_code == 202
        body = _wait_terminal(client, r.json()["id"])
        assert body["status"] == "success"
    finally:
        client.delete("/workflows/saved_hello")


def test_run_unknown_saved_workflow_returns_404(client: TestClient):
    r = client.post("/jobs/run", json={"workflow_name": "__nope__"})
    assert r.status_code == 404


# ---------- WebSocket ----------

def test_websocket_streams_full_history_until_done(client: TestClient):
    job_id = client.post("/jobs/run", json=INLINE_HELLO).json()["id"]
    received: list[dict] = []
    with client.websocket_connect(f"/ws/jobs/{job_id}") as ws:
        for _ in range(50):
            entry = ws.receive_json()
            received.append(entry)
            if entry["level"] == "done":
                break
    assert received, "WS sent no entries"
    assert received[-1]["level"] == "done"
    assert any(e["level"] == "info" for e in received)


def test_websocket_replays_history_for_completed_job(client: TestClient):
    """WS, підключений ПІСЛЯ завершення job, має побачити всі логи (replay)."""
    job_id = client.post("/jobs/run", json=INLINE_HELLO).json()["id"]
    _wait_terminal(client, job_id)
    received: list[dict] = []
    with client.websocket_connect(f"/ws/jobs/{job_id}") as ws:
        for _ in range(50):
            entry = ws.receive_json()
            received.append(entry)
            if entry["level"] == "done":
                break
    assert received[-1]["level"] == "done"
    assert len(received) >= 3  # хоча б start, exec, done
