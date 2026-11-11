import jwt

from app import auth

from .conftest import register_and_login


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_register_success_does_not_leak_password(client):
    res = client.post("/api/auth/register", json={"username": "alice", "password": "secret123"})
    assert res.status_code == 201
    body = res.json()
    assert body["username"] == "alice"
    assert "password" not in body and "password_hash" not in body


def test_register_duplicate_username(client):
    payload = {"username": "alice", "password": "secret123"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    assert client.post("/api/auth/register", json=payload).status_code == 409


def test_register_validation(client):
    assert client.post("/api/auth/register", json={"username": "ab", "password": "secret123"}).status_code == 422
    assert client.post("/api/auth/register", json={"username": "alice", "password": "123"}).status_code == 422
    assert client.post("/api/auth/register", json={"username": "bad name!", "password": "secret123"}).status_code == 422


def test_login_success_and_me(client):
    headers = register_and_login(client)
    res = client.get("/api/auth/me", headers=headers)
    assert res.status_code == 200
    assert res.json()["username"] == "alice"


def test_login_wrong_password(client):
    client.post("/api/auth/register", json={"username": "alice", "password": "secret123"})
    res = client.post("/api/auth/login", data={"username": "alice", "password": "wrong-pass"})
    assert res.status_code == 401


def test_login_unknown_user(client):
    res = client.post("/api/auth/login", data={"username": "ghost", "password": "whatever1"})
    assert res.status_code == 401


def test_protected_route_requires_token(client):
    assert client.get("/api/tasks").status_code == 401
    assert client.get("/api/tasks", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_expired_token_rejected(client):
    register_and_login(client)
    expired = auth.create_access_token("alice", expires_minutes=-1)
    res = client.get("/api/tasks", headers={"Authorization": f"Bearer {expired}"})
    assert res.status_code == 401


def test_token_signed_with_wrong_key_rejected(client):
    register_and_login(client)
    forged = jwt.encode({"sub": "alice"}, "x" * 40, algorithm="HS256")
    res = client.get("/api/tasks", headers={"Authorization": f"Bearer {forged}"})
    assert res.status_code == 401


def test_password_hashing_roundtrip():
    hashed = auth.hash_password("hunter22")
    assert hashed != "hunter22"
    assert auth.verify_password("hunter22", hashed)
    assert not auth.verify_password("hunter23", hashed)
    # Salted: hashing twice gives different results
    assert auth.hash_password("hunter22") != hashed


def test_verify_password_handles_garbage_hash():
    assert auth.verify_password("x", "not-a-valid-hash") is False
