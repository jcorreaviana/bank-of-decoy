import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chaos import ChaosMiddleware, register_chaos_router
from chaos import middleware as chaos_middleware
from chaos import runtime_config as runtime_config_module
from chaos.internal_auth import TOKEN_ENV_VAR, TOKEN_HEADER
from chaos.runtime_config import clear_runtime_override, get_runtime_override


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ChaosMiddleware)
    register_chaos_router(app)

    @app.get("/v1/widgets")
    def _widget() -> dict:
        return {"ok": True}

    return app


@pytest.fixture(autouse=True)
def _clean_chaos_state(monkeypatch):
    for key in ("CHAOS_ENABLED", "CHAOS_FAILURE_RATE", "CHAOS_FAILURE_TYPES", TOKEN_ENV_VAR):
        monkeypatch.delenv(key, raising=False)
    clear_runtime_override()
    yield
    clear_runtime_override()


def test_post_without_token_is_forbidden(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, "s3cret")
    client = TestClient(_build_app())

    response = client.post("/internal/chaos/config", json={"enabled": True, "failure_types": ["500"]})

    assert response.status_code == 403
    body = response.json()
    assert body["error_code"] == "CHAOS_CONFIG_FORBIDDEN"
    assert get_runtime_override() is None


def test_post_with_wrong_token_is_forbidden(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, "s3cret")
    client = TestClient(_build_app())

    response = client.post(
        "/internal/chaos/config",
        json={"enabled": True, "failure_types": ["500"]},
        headers={TOKEN_HEADER: "wrong-token"},
    )

    assert response.status_code == 403


def test_post_when_token_env_var_unset_is_forbidden_even_without_header(monkeypatch):
    # Fail closed: sem CHAOS_INTERNAL_TOKEN configurado, nao ha um modo
    # aberto por omissao - nem mandando qualquer header ajuda.
    client = TestClient(_build_app())

    response = client.post(
        "/internal/chaos/config",
        json={"enabled": True, "failure_types": ["500"]},
        headers={TOKEN_HEADER: "anything"},
    )

    assert response.status_code == 403


def test_post_with_correct_token_updates_config_and_returns_it(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, "s3cret")
    client = TestClient(_build_app())

    response = client.post(
        "/internal/chaos/config",
        json={"enabled": True, "failure_rate": 1.0, "failure_types": ["500"]},
        headers={TOKEN_HEADER: "s3cret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "enabled": True,
        "failure_rate": 1.0,
        "failure_types": ["500"],
        "expires_at": None,
        "ramp_ceiling_seconds": 3.0,
        "ramp_window_seconds": 300.0,
        "lag_increment_ms": 200.0,
        "lag_ceiling_ms": 5000.0,
        "kafka_delay_seconds": 3.0,
    }


def test_post_accepts_and_echoes_fase_2b_type_specific_params(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, "s3cret")
    client = TestClient(_build_app())

    response = client.post(
        "/internal/chaos/config",
        json={
            "enabled": True,
            "failure_types": ["degradacao_progressiva", "kafka_lag", "kafka_delay"],
            "ramp_ceiling_seconds": 5.0,
            "ramp_window_seconds": 120.0,
            "lag_increment_ms": 50.0,
            "lag_ceiling_ms": 1000.0,
            "kafka_delay_seconds": 1.0,
        },
        headers={TOKEN_HEADER: "s3cret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ramp_ceiling_seconds"] == 5.0
    assert body["ramp_window_seconds"] == 120.0
    assert body["lag_increment_ms"] == 50.0
    assert body["lag_ceiling_ms"] == 1000.0
    assert body["kafka_delay_seconds"] == 1.0

    from chaos.runtime_config import get_active_type_params

    params = get_active_type_params()
    assert params.ramp_ceiling_seconds == 5.0
    assert params.lag_increment_ms == 50.0


def test_post_with_unknown_failure_type_is_rejected_with_validation_error(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, "s3cret")
    client = TestClient(_build_app())

    response = client.post(
        "/internal/chaos/config",
        json={"enabled": True, "failure_types": ["nao_existe"]},
        headers={TOKEN_HEADER: "s3cret"},
    )

    assert response.status_code == 422


def test_config_change_takes_effect_without_restart(monkeypatch):
    """Nucleo do criterio de aceite: ajustar via POST muda o
    comportamento do ChaosMiddleware na proxima requisicao, sem precisar
    reiniciar o processo (nao ha restart possivel dentro de um teste -
    o mesmo `app`/`client` seguem no ar o tempo todo)."""
    monkeypatch.setenv(TOKEN_ENV_VAR, "s3cret")
    monkeypatch.setattr(chaos_middleware.random, "random", lambda: 0.0)
    monkeypatch.setattr(chaos_middleware.random, "choice", lambda choices: "500")
    client = TestClient(_build_app(), raise_server_exceptions=False)

    before = client.get("/v1/widgets")
    assert before.status_code == 200

    config_response = client.post(
        "/internal/chaos/config",
        json={"enabled": True, "failure_rate": 1.0, "failure_types": ["500"]},
        headers={TOKEN_HEADER: "s3cret"},
    )
    assert config_response.status_code == 200

    after = client.get("/v1/widgets")
    assert after.status_code == 500


def test_env_var_fallback_still_works_when_endpoint_never_called(monkeypatch):
    monkeypatch.setenv("CHAOS_ENABLED", "true")
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "1.0")
    monkeypatch.setenv("CHAOS_FAILURE_TYPES", "503")
    monkeypatch.setattr(chaos_middleware.random, "random", lambda: 0.0)
    monkeypatch.setattr(chaos_middleware.random, "choice", lambda choices: "503")
    client = TestClient(_build_app())

    response = client.get("/v1/widgets")

    assert response.status_code == 503
    assert response.json()["error_code"] == "CHAOS_SERVICE_UNAVAILABLE"


def test_config_reverts_to_env_fallback_after_duration_expires(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV_VAR, "s3cret")
    monkeypatch.setenv("CHAOS_ENABLED", "false")
    monkeypatch.setattr(chaos_middleware.random, "random", lambda: 0.0)
    monkeypatch.setattr(runtime_config_module.time, "monotonic", lambda: 1000.0)
    client = TestClient(_build_app())

    config_response = client.post(
        "/internal/chaos/config",
        json={"enabled": True, "failure_rate": 1.0, "failure_types": ["503"], "duration_seconds": 30.0},
        headers={TOKEN_HEADER: "s3cret"},
    )
    assert config_response.status_code == 200

    monkeypatch.setattr(runtime_config_module.time, "monotonic", lambda: 1010.0)
    still_active = client.get("/v1/widgets")
    assert still_active.status_code == 503

    monkeypatch.setattr(runtime_config_module.time, "monotonic", lambda: 1031.0)
    expired = client.get("/v1/widgets")
    assert expired.status_code == 200
