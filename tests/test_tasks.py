from .conftest import register_and_login


def make_task(client, headers, **overrides):
    payload = {"title": "Write report", "priority": "high", "due_date": "2030-01-15"}
    payload.update(overrides)
    return client.post("/api/tasks", json=payload, headers=headers)


def test_create_task(client, auth_headers):
    res = make_task(client, auth_headers)
    assert res.status_code == 201
    body = res.json()
    assert body["title"] == "Write report"
    assert body["priority"] == "high"
    assert body["status"] == "todo"
    assert body["due_date"] == "2030-01-15"
    assert body["id"] > 0


def test_create_task_defaults(client, auth_headers):
    body = client.post("/api/tasks", json={"title": "Minimal"}, headers=auth_headers).json()
    assert body["priority"] == "medium"
    assert body["status"] == "todo"
    assert body["description"] == ""
    assert body["due_date"] is None


def test_create_task_validation(client, auth_headers):
    assert client.post("/api/tasks", json={"title": ""}, headers=auth_headers).status_code == 422
    assert client.post("/api/tasks", json={}, headers=auth_headers).status_code == 422
    bad_priority = {"title": "x", "priority": "urgent"}
    assert client.post("/api/tasks", json=bad_priority, headers=auth_headers).status_code == 422


def test_list_tasks_newest_first(client, auth_headers):
    make_task(client, auth_headers, title="first")
    make_task(client, auth_headers, title="second")
    titles = [t["title"] for t in client.get("/api/tasks", headers=auth_headers).json()]
    assert titles == ["second", "first"]


def test_filter_by_status_and_priority(client, auth_headers):
    make_task(client, auth_headers, title="a", priority="high")
    make_task(client, auth_headers, title="b", priority="low", status="done")
    make_task(client, auth_headers, title="c", priority="low")

    done = client.get("/api/tasks?status=done", headers=auth_headers).json()
    assert [t["title"] for t in done] == ["b"]

    low = client.get("/api/tasks?priority=low", headers=auth_headers).json()
    assert {t["title"] for t in low} == {"b", "c"}

    both = client.get("/api/tasks?priority=low&status=todo", headers=auth_headers).json()
    assert [t["title"] for t in both] == ["c"]

    assert client.get("/api/tasks?status=bogus", headers=auth_headers).status_code == 422


def test_get_task(client, auth_headers):
    task_id = make_task(client, auth_headers).json()["id"]
    res = client.get(f"/api/tasks/{task_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["id"] == task_id


def test_partial_update(client, auth_headers):
    task_id = make_task(client, auth_headers).json()["id"]
    res = client.put(f"/api/tasks/{task_id}", json={"status": "in_progress"}, headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "in_progress"
    assert body["title"] == "Write report"  # untouched
    assert body["priority"] == "high"  # untouched


def test_update_can_clear_due_date_but_not_title(client, auth_headers):
    task_id = make_task(client, auth_headers).json()["id"]
    res = client.put(
        f"/api/tasks/{task_id}", json={"due_date": None, "title": None}, headers=auth_headers
    )
    assert res.status_code == 200
    assert res.json()["due_date"] is None
    assert res.json()["title"] == "Write report"


def test_delete_task(client, auth_headers):
    task_id = make_task(client, auth_headers).json()["id"]
    assert client.delete(f"/api/tasks/{task_id}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/tasks/{task_id}", headers=auth_headers).status_code == 404
    assert client.get("/api/tasks", headers=auth_headers).json() == []


def test_missing_task_returns_404(client, auth_headers):
    assert client.get("/api/tasks/999", headers=auth_headers).status_code == 404
    assert client.put("/api/tasks/999", json={"title": "x"}, headers=auth_headers).status_code == 404
    assert client.delete("/api/tasks/999", headers=auth_headers).status_code == 404


def test_users_cannot_access_each_others_tasks(client):
    alice = register_and_login(client, "alice", "secret123")
    bob = register_and_login(client, "bob", "secret456")

    task_id = make_task(client, alice, title="alice private").json()["id"]

    assert client.get("/api/tasks", headers=bob).json() == []
    assert client.get(f"/api/tasks/{task_id}", headers=bob).status_code == 404
    assert client.put(f"/api/tasks/{task_id}", json={"title": "hacked"}, headers=bob).status_code == 404
    assert client.delete(f"/api/tasks/{task_id}", headers=bob).status_code == 404

    # Still intact for the owner
    assert client.get(f"/api/tasks/{task_id}", headers=alice).json()["title"] == "alice private"


def test_frontend_is_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "AI" in res.text and "Task Manager" in res.text
