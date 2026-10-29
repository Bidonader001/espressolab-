import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("ENABLE_SCHEDULER", "0")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-espressolab")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test-pass-123")
    monkeypatch.setenv("ALLOW_SIMULATOR", "1")
    monkeypatch.setenv("FERNET_KEY", "")
    from app.database import reset

    reset()
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
    reset()


@pytest.fixture()
def auth(client: TestClient):
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "test-pass-123"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}
