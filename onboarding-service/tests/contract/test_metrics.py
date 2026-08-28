from fastapi.testclient import TestClient

from app.main import app


def test_metrics_exposes_golden_signals() -> None:
    client = TestClient(app)
    client.get("/health")

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body
    assert "db_pool_connections_in_use" in body


def test_metrics_expoe_metricas_de_negocio_v1() -> None:
    """specs/business/15-metricas-negocio.md - nome/tipo da metrica fica
    visivel em /metrics assim que o app sobe (antes de qualquer incremento
    real), entao este teste nao precisa de banco."""
    client = TestClient(app)

    response = client.get("/metrics")

    body = response.text
    assert "onboarding_resultado_total" in body
    assert "risco_sinal_total" in body
