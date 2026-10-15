"""Behavior-focused tests for the initial health route."""

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health_endpoint_returns_expected_contract() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "sitara-api"}
    assert response.headers["content-type"].startswith("application/json")


def test_unknown_endpoint_is_not_accidentally_exposed() -> None:
    response = client.get("/api/v1/internal-debug")

    assert response.status_code == 404
