"""API tests driven through FastAPI's TestClient."""

from fastapi.testclient import TestClient

from app import __version__
from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_add_endpoint() -> None:
    response = client.get("/add", params={"a": 2, "b": 3})
    assert response.status_code == 200
    assert response.json() == {"result": 5}


def test_divide_endpoint() -> None:
    response = client.get("/divide", params={"a": 9, "b": 3})
    assert response.status_code == 200
    assert response.json() == {"result": 3}


def test_divide_endpoint_by_zero_returns_400() -> None:
    response = client.get("/divide", params={"a": 1, "b": 0})
    assert response.status_code == 400
    assert "division by zero" in response.json()["detail"]
