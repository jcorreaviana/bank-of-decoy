import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app
from chaos.internal_auth import TOKEN_ENV_VAR, TOKEN_HEADER
from chaos.runtime_config import clear_runtime_override


@pytest.fixture(autouse=True)
def _clean_chaos_state(monkeypatch):
    for key in ("CHAOS_ENABLED", "CHAOS_FAILURE_RATE", "CHAOS_FAILURE_TYPES", TOKEN_ENV_VAR):
        monkeypatch.delenv(key, raising=False)
    clear_runtime_override()
    yield
    clear_runtime_override()


def test_config_endpoint_rejects_request_without_internal_token(monkeypatch) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "s3cret")
    client = TestClient(app)

    response = client.post("/internal/chaos/config", json={"enabled": True, "failure_types": ["503"]})

    assert response.status_code == 403
    assert response.json()["error_code"] == "CHAOS_CONFIG_FORBIDDEN"


def test_config_endpoint_rejects_request_when_token_not_configured(monkeypatch) -> None:
    # CHAOS_INTERNAL_TOKEN nao definido - fail closed, mesmo com um header
    # qualquer no request (nao existe um modo aberto por omissao).
    client = TestClient(app)

    response = client.post(
        "/internal/chaos/config",
        json={"enabled": True, "failure_types": ["503"]},
        headers={TOKEN_HEADER: "qualquer-coisa"},
    )

    assert response.status_code == 403


def test_config_change_takes_effect_without_restarting_the_process(monkeypatch) -> None:
    # Nao ha "antes"/"depois" contra a mesma rota de negocio aqui de
    # proposito: `/v1/accounts/{id}` depende de banco (Depends(get_db)),
    # e specs/tech/testing.md exige isolamento de banco nos testes de
    # contrato - o 503 abaixo so pode vir do override setado pelo POST
    # (chaos desligado por padrao), sem precisar de um banco no ar so
    # para observar o estado "antes" (mesmo padrao ja usado em
    # test_chaos.py::test_chaos_enabled_injects_503_...).
    monkeypatch.setenv(TOKEN_ENV_VAR, "s3cret")
    client = TestClient(app)
    account_url = f"/v1/accounts/{uuid.uuid4()}"

    config_response = client.post(
        "/internal/chaos/config",
        json={"enabled": True, "failure_rate": 1.0, "failure_types": ["503"]},
        headers={TOKEN_HEADER: "s3cret"},
    )
    assert config_response.status_code == 200
    assert config_response.json() == {
        "enabled": True,
        "failure_rate": 1.0,
        "failure_types": ["503"],
        "expires_at": None,
        "ramp_ceiling_seconds": 3.0,
        "ramp_window_seconds": 300.0,
        "lag_increment_ms": 200.0,
        "lag_ceiling_ms": 5000.0,
        "kafka_delay_seconds": 3.0,
    }

    after = client.get(account_url)
    assert after.status_code == 503
    assert after.json()["error_code"] == "CHAOS_SERVICE_UNAVAILABLE"


def test_env_var_fallback_still_works_when_config_endpoint_never_called(monkeypatch) -> None:
    monkeypatch.setenv("CHAOS_ENABLED", "true")
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "1.0")
    monkeypatch.setenv("CHAOS_FAILURE_TYPES", "503")
    client = TestClient(app)

    response = client.get(f"/v1/accounts/{uuid.uuid4()}")

    assert response.status_code == 503
    assert response.json()["error_code"] == "CHAOS_SERVICE_UNAVAILABLE"
