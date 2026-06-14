"""Smoke test for /health endpoint.

Phase 01 acceptance: backend boots, /health returns 200.
Full integration tests added per-phase (see plan).
"""

from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_ok() -> None:
    """GET /health returns 200 with status=ok."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_endpoint_returns_prometheus_format() -> None:
    """GET /metrics returns 200 with Prometheus text format."""
    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert b"kg_api_requests_total" in response.content


def test_api_root_returns_info() -> None:
    """GET /api/v1 returns API info."""
    client = TestClient(app)
    response = client.get("/api/v1")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "KnowGate API"
    assert "version" in data
