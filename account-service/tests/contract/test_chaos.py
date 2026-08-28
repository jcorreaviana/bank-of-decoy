import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(autouse=True)
def _clean_chaos_env(monkeypatch):
    for key in ("CHAOS_ENABLED", "CHAOS_FAILURE_RATE", "CHAOS_FAILURE_TYPES"):
        monkeypatch.delenv(key, raising=False)


def test_chaos_disabled_by_default_does_not_affect_health() -> None:
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chaos_enabled_injects_503_and_is_still_counted_by_metrics(monkeypatch) -> None:
    monkeypatch.setenv("CHAOS_ENABLED", "true")
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "1.0")
    monkeypatch.setenv("CHAOS_FAILURE_TYPES", "503")
    client = TestClient(app)

    response = client.get(f"/v1/accounts/{uuid.uuid4()}")

    assert response.status_code == 503
    assert response.json()["error_code"] == "CHAOS_SERVICE_UNAVAILABLE"

    # MetricsMiddleware precisa contar a falha injetada (chaos precisa ser a
    # camada mais interna, ver shared/chaos/chaos/middleware.py) - senao o
    # dashboard Grafana nunca mostraria efeito ao ligar o caos.
    metrics_body = client.get("/metrics").text
    assert (
        'http_requests_total{method="GET",route="/v1/accounts/{account_id}",status_code="503"}' in metrics_body
    )


def test_chaos_enabled_at_full_rate_still_exempts_health_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("CHAOS_ENABLED", "true")
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "1.0")
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
