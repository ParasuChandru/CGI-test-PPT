import time

import pytest

import studio

from conftest import SAMPLE_DIR


@pytest.fixture(autouse=True)
def _clean_globals(tmp_path, monkeypatch):
    monkeypatch.setattr(studio, "WORKSPACES_DIR", str(tmp_path / "workspaces"))
    studio.JOBS.clear()
    studio.REPOS.clear()
    studio._INFLIGHT.clear()
    studio.app.testing = True
    yield
    studio.JOBS.clear()
    studio.REPOS.clear()
    studio._INFLIGHT.clear()


@pytest.fixture
def client():
    return studio.app.test_client()


def _connect_and_wait(client, payload, timeout=30):
    r = client.post("/api/connect", json=payload)
    assert r.status_code == 200
    job_id = r.get_json()["job_id"]
    deadline = time.time() + timeout
    body = None
    while time.time() < deadline:
        body = client.get(f"/api/job/{job_id}").get_json()
        if body["status"] != "running":
            break
        time.sleep(0.05)
    return job_id, body


def test_invalid_url_not_a_url(client):
    r = client.post("/api/connect", json={"url": "not-a-url"})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_invalid_url_with_semicolon(client):
    r = client.post("/api/connect", json={"url": "https://example.com/repo.git;rm -rf /"})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_unknown_repo_returns_404(client):
    r = client.get("/api/nope/search?q=x")
    assert r.status_code == 404
    assert r.get_json()["error"] == "repo not indexed"

    r = client.get("/api/nope/impact?name=x")
    assert r.status_code == 404

    r = client.get("/api/nope/file_impact?path=x")
    assert r.status_code == 404

    r = client.post("/api/nope/impact_from_diff", json={"diff_text": "x"})
    assert r.status_code == 404


def test_unknown_job_returns_404(client):
    r = client.get("/api/job/does-not-exist")
    assert r.status_code == 404


def test_job_status_transitions_from_running_to_done(tmp_path):
    job_id = "test-job-1"
    studio.JOBS[job_id] = {
        "status": "running", "phase": "queued", "message": "Queued…",
        "repo": None, "stats": None, "error": None,
    }
    assert studio.JOBS[job_id]["status"] == "running"
    studio._run_connect_job(job_id, path=SAMPLE_DIR)
    assert studio.JOBS[job_id]["status"] == "done"
    assert studio.JOBS[job_id]["repo"] in studio.REPOS


def test_nonexistent_local_path_clean_error(client):
    r = client.post("/api/connect", json={"path": "/definitely/does/not/exist"})
    assert r.status_code == 400
    body = r.get_json()
    assert "error" in body
    assert "not found" in body["error"] or "not a directory" in body["error"]


def test_local_path_missing_returns_400_at_connect_time(client):
    r = client.post("/api/connect", json={"path": "/definitely/does/not/exist"})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_impact_from_diff_empty_body(client):
    job_id, body = _connect_and_wait(client, {"path": SAMPLE_DIR})
    assert body["status"] == "done"
    repo_key = body["repo"]
    r = client.post(f"/api/{repo_key}/impact_from_diff", json={})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_full_connect_search_impact_flow(client):
    job_id, body = _connect_and_wait(client, {"path": SAMPLE_DIR})
    assert body["status"] == "done"
    repo_key = body["repo"]

    r = client.get("/api/repos")
    assert r.status_code == 200
    keys = [repo["key"] for repo in r.get_json()]
    assert repo_key in keys

    r = client.get(f"/api/{repo_key}/search?q=format_name")
    assert r.status_code == 200
    assert any(item["name"] == "format_name" for item in r.get_json())

    r = client.get(f"/api/{repo_key}/impact?name=format_name")
    assert r.status_code == 200
    assert "get_user" in r.get_json()["impacted_symbols"]


def test_index_page_serves_ui(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"Impact Studio" in r.data or b"Connect a repository" in r.data
