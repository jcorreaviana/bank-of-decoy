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
    client = TestClient(app)

    response = client.post(
        "/internal/chaos/config",
        json={"enabled": True, "failure_types": ["503"]},
        headers={TOKEN_HEADER: "qualquer-coisa"},
    )

    assert response.status_code == 403


def test_config_change_takes_effect_without_restarting_the_process(monkeypatch) -> None:
    # Rota de negocio depende de banco (Depends(get_db)) - o 503 abaixo so
    # pode vir do override setado pelo POST, ja que chaos vem desligado por
    # padrao (specs/tech/testing.md exige isolamento de banco nos testes).
    monkeypatch.setenv(TOKEN_ENV_VAR, "s3cret")
    client = TestClient(app)

    config_response = client.post(
        "/internal/chaos/config",
        json={"enabled": True, "failure_rate": 1.0, "failure_types": ["503"]},
        headers={TOKEN_HEADER: "s3cret"},
    )
    assert config_response.status_code == 200

    response = client.get(f"/v1/onboarding/{uuid.uuid4()}")

    assert response.status_code == 503
    assert response.json()["error_code"] == "CHAOS_SERVICE_UNAVAILABLE"


def test_env_var_fallback_still_works_when_config_endpoint_never_called(monkeypatch) -> None:
    monkeypatch.setenv("CHAOS_ENABLED", "true")
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "1.0")
    monkeypatch.setenv("CHAOS_FAILURE_TYPES", "503")
    client = TestClient(app)

    response = client.get(f"/v1/onboarding/{uuid.uuid4()}")

    assert response.status_code == 503
    assert response.json()["error_code"] == "CHAOS_SERVICE_UNAVAILABLE"
