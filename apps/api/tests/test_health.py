from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoint_returns_ok():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_local_vite_origin_can_call_the_api_but_remote_origins_cannot():
    client = TestClient(create_app())

    local = client.get("/health", headers={"Origin": "http://127.0.0.1:5173"})
    remote = client.get("/health", headers={"Origin": "https://example.com"})

    assert local.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "access-control-allow-origin" not in remote.headers
