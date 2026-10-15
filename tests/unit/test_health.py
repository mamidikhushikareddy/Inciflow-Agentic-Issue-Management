from fastapi.testclient import TestClient

from inciflow.main import app

client = TestClient(app)


def test_root_returns_application_identity() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "application": "Inciflow",
        "version": "0.1.0",
        "status": "running",
    }


def test_liveness_endpoint() -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_unknown_route_returns_404() -> None:
    response = client.get("/this-route-does-not-exist")

    assert response.status_code == 404
