import pytest
from fastapi.testclient import TestClient

from api.config import Settings, get_settings
from api.main import VERSION, app


@pytest.fixture
def client(tmp_path):
    app.dependency_overrides[get_settings] = lambda: Settings(
        db_path=str(tmp_path / "test.sqlite3")
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_hello(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"message": "Hello, World!"}


def test_health_uses_db(client, tmp_path):
    resp = client.get("/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": VERSION}
    assert (tmp_path / "test.sqlite3").exists()


def test_cors_allows_app_origin(client):
    resp = client.options(
        "/v1/connectors",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_rejects_other_origin(client):
    resp = client.get("/v1/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in resp.headers


def test_cors_origins_from_env(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("SCOOP_CORS_ORIGINS", "http://a.test, http://b.test")
    try:
        assert get_settings().cors_origins == ("http://a.test", "http://b.test")
    finally:
        get_settings.cache_clear()
