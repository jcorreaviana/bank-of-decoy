import logging

import pytest
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from chaos import ChaosInjectedError, ChaosMiddleware
from chaos import middleware as chaos_middleware
from chaos.known_types import KNOWN_FAILURE_TYPES
from chaos.runtime_config import ChaosTypeParams, clear_runtime_override, set_runtime_override


async def _ok_endpoint(request):
    return JSONResponse({"ok": True})


async def _health_endpoint(request):
    return JSONResponse({"status": "ok"})


async def _metrics_endpoint(request):
    return JSONResponse({"metrics": "ok"})


async def _widget_detail_endpoint(request):
    return JSONResponse({"widget_id": request.path_params["widget_id"]})


def _build_app() -> Starlette:
    app = Starlette(
        routes=[
            Route("/v1/widgets", _ok_endpoint),
            Route("/v1/widgets/{widget_id}", _widget_detail_endpoint),
            Route("/health", _health_endpoint),
            Route("/metrics", _metrics_endpoint),
        ]
    )
    app.add_middleware(ChaosMiddleware)
    return app


class _RouteCapturingMiddleware(BaseHTTPMiddleware):
    """Mimica o que app/core/metrics.py:MetricsMiddleware le de
    request.scope apos call_next, para provar que o path template (nao o
    path com valores reais interpolados) fica disponivel mesmo quando o
    caos curto-circuita antes do Router rodar."""

    def __init__(self, app, captured: list):
        super().__init__(app)
        self._captured = captured

    async def dispatch(self, request, call_next):
        # try/finally, nao so o caminho feliz: e assim que a
        # MetricsMiddleware real (account-service/app/core/metrics.py e
        # equivalentes) le request.scope mesmo quando call_next levanta uma
        # excecao nao tratada (failure_type "500").
        try:
            return await call_next(request)
        finally:
            route = request.scope.get("route")
            self._captured.append(route.path if route is not None else request.url.path)


def _build_app_with_route_capture(captured: list) -> Starlette:
    app = _build_app()
    app.add_middleware(_RouteCapturingMiddleware, captured=captured)
    return app


@pytest.fixture(autouse=True)
def _clean_chaos_env(monkeypatch):
    for key in ("CHAOS_ENABLED", "CHAOS_FAILURE_RATE", "CHAOS_FAILURE_TYPES"):
        monkeypatch.delenv(key, raising=False)
    # Isola de overrides de runtime (chaos/runtime_config.py, issue #51)
    # deixados por outro teste - o store e um singleton por processo.
    clear_runtime_override()


def test_disabled_by_default_passes_through(monkeypatch):
    monkeypatch.setattr(chaos_middleware.random, "random", lambda: 0.0)
    client = TestClient(_build_app())

    response = client.get("/v1/widgets")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_enabled_but_roll_above_rate_passes_through(monkeypatch):
    monkeypatch.setenv("CHAOS_ENABLED", "true")
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "0.05")
    monkeypatch.setattr(chaos_middleware.random, "random", lambda: 0.5)
    client = TestClient(_build_app())

    response = client.get("/v1/widgets")

    assert response.status_code == 200


@pytest.mark.parametrize("path", ["/health", "/metrics"])
def test_exempt_paths_never_injected_even_at_full_rate(monkeypatch, path):
    monkeypatch.setenv("CHAOS_ENABLED", "true")
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "1.0")
    monkeypatch.setattr(chaos_middleware.random, "random", lambda: 0.0)
    client = TestClient(_build_app())

    response = client.get(path)

    assert response.status_code == 200


def test_503_injection_short_circuits_without_calling_endpoint(monkeypatch):
    monkeypatch.setenv("CHAOS_ENABLED", "true")
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "1.0")
    monkeypatch.setenv("CHAOS_FAILURE_TYPES", "503")
    monkeypatch.setattr(chaos_middleware.random, "random", lambda: 0.0)
    monkeypatch.setattr(chaos_middleware.random, "choice", lambda choices: "503")
    client = TestClient(_build_app())

    response = client.get("/v1/widgets")

    assert response.status_code == 503
    body = response.json()
    assert body["error_code"] == "CHAOS_SERVICE_UNAVAILABLE"
    assert body["trace_id"]


def test_500_injection_raises_chaos_injected_error(monkeypatch):
    monkeypatch.setenv("CHAOS_ENABLED", "true")
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "1.0")
    monkeypatch.setenv("CHAOS_FAILURE_TYPES", "500")
    monkeypatch.setattr(chaos_middleware.random, "random", lambda: 0.0)
    monkeypatch.setattr(chaos_middleware.random, "choice", lambda choices: "500")
    client = TestClient(_build_app(), raise_server_exceptions=True)

    with pytest.raises(ChaosInjectedError) as exc_info:
        client.get("/v1/widgets")

    assert exc_info.value.chaos_injected is True


async def _instant_sleep(_seconds):
    return None


def test_latencia_injection_delays_then_returns_real_response(monkeypatch):
    monkeypatch.setenv("CHAOS_ENABLED", "true")
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "1.0")
    monkeypatch.setenv("CHAOS_FAILURE_TYPES", "latencia")
    monkeypatch.setattr(chaos_middleware.random, "random", lambda: 0.0)
    monkeypatch.setattr(chaos_middleware.random, "choice", lambda choices: "latencia")
    sleep_calls = []

    async def _tracked_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(chaos_middleware.asyncio, "sleep", _tracked_sleep)
    client = TestClient(_build_app())

    response = client.get("/v1/widgets")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert sleep_calls == [chaos_middleware._LATENCY_DELAY_SECONDS]


def test_timeout_injection_delays_then_returns_504(monkeypatch):
    monkeypatch.setenv("CHAOS_ENABLED", "true")
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "1.0")
    monkeypatch.setenv("CHAOS_FAILURE_TYPES", "timeout")
    monkeypatch.setattr(chaos_middleware.random, "random", lambda: 0.0)
    monkeypatch.setattr(chaos_middleware.random, "choice", lambda choices: "timeout")
    sleep_calls = []

    async def _tracked_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(chaos_middleware.asyncio, "sleep", _tracked_sleep)
    client = TestClient(_build_app())

    response = client.get("/v1/widgets")

    assert response.status_code == 504
    assert response.json()["error_code"] == "CHAOS_TIMEOUT_INJECTED"
    assert sleep_calls == [chaos_middleware._TIMEOUT_DELAY_SECONDS]


def test_injection_logs_warning_with_chaos_injected_context(monkeypatch, caplog):
    monkeypatch.setenv("CHAOS_ENABLED", "true")
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "1.0")
    monkeypatch.setenv("CHAOS_FAILURE_TYPES", "503")
    monkeypatch.setattr(chaos_middleware.random, "random", lambda: 0.0)
    monkeypatch.setattr(chaos_middleware.random, "choice", lambda choices: "503")
    client = TestClient(_build_app())

    with caplog.at_level(logging.WARNING, logger="chaos"):
        client.get("/v1/widgets")

    [record] = [r for r in caplog.records if r.name == "chaos"]
    assert record.context["chaos_injected"] is True
    assert record.context["failure_type"] == "503"
    assert record.context["route"] == "/v1/widgets"
    assert record.context["method"] == "GET"


def test_503_injection_preserves_route_template_for_metrics(monkeypatch):
    monkeypatch.setenv("CHAOS_ENABLED", "true")
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "1.0")
    monkeypatch.setenv("CHAOS_FAILURE_TYPES", "503")
    monkeypatch.setattr(chaos_middleware.random, "random", lambda: 0.0)
    monkeypatch.setattr(chaos_middleware.random, "choice", lambda choices: "503")
    captured: list = []
    client = TestClient(_build_app_with_route_capture(captured))

    response = client.get("/v1/widgets/abc-123")

    assert response.status_code == 503
    assert captured == ["/v1/widgets/{widget_id}"]


def test_timeout_injection_preserves_route_template_for_metrics(monkeypatch):
    monkeypatch.setenv("CHAOS_ENABLED", "true")
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "1.0")
    monkeypatch.setenv("CHAOS_FAILURE_TYPES", "timeout")
    monkeypatch.setattr(chaos_middleware.random, "random", lambda: 0.0)
    monkeypatch.setattr(chaos_middleware.random, "choice", lambda choices: "timeout")
    monkeypatch.setattr(chaos_middleware.asyncio, "sleep", _instant_sleep)
    captured: list = []
    client = TestClient(_build_app_with_route_capture(captured))

    response = client.get("/v1/widgets/abc-123")

    assert response.status_code == 504
    assert captured == ["/v1/widgets/{widget_id}"]


def test_500_injection_preserves_route_template_for_metrics(monkeypatch):
    monkeypatch.setenv("CHAOS_ENABLED", "true")
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "1.0")
    monkeypatch.setenv("CHAOS_FAILURE_TYPES", "500")
    monkeypatch.setattr(chaos_middleware.random, "random", lambda: 0.0)
    monkeypatch.setattr(chaos_middleware.random, "choice", lambda choices: "500")
    captured: list = []
    app = _build_app_with_route_capture(captured)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/v1/widgets/abc-123")

    assert response.status_code == 500
    assert captured == ["/v1/widgets/{widget_id}"]


def test_load_config_defaults_when_unset():
    enabled, failure_rate, failure_types = chaos_middleware._load_config()

    assert enabled is False
    assert failure_rate == 0.05
    assert set(failure_types) == KNOWN_FAILURE_TYPES


def test_load_config_falls_back_on_invalid_rate(monkeypatch):
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "not-a-float")

    _, failure_rate, _ = chaos_middleware._load_config()

    assert failure_rate == 0.05


def test_load_config_filters_unknown_types_and_falls_back_when_empty(monkeypatch):
    monkeypatch.setenv("CHAOS_FAILURE_TYPES", "made_up,also_fake")

    _, _, failure_types = chaos_middleware._load_config()

    assert set(failure_types) == KNOWN_FAILURE_TYPES


def test_load_config_keeps_only_known_types(monkeypatch):
    monkeypatch.setenv("CHAOS_FAILURE_TYPES", "503, made_up ,500")

    _, _, failure_types = chaos_middleware._load_config()

    assert set(failure_types) == {"503", "500"}


def test_load_config_prefers_runtime_override_over_env(monkeypatch):
    monkeypatch.setenv("CHAOS_ENABLED", "false")
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "0.05")
    from chaos.runtime_config import set_runtime_override

    set_runtime_override(enabled=True, failure_rate=0.9, failure_types=["500"], duration_seconds=None)

    enabled, failure_rate, failure_types = chaos_middleware._load_config()

    assert (enabled, failure_rate, failure_types) == (True, 0.9, ["500"])


def test_degradacao_progressiva_delay_grows_with_elapsed_time(monkeypatch):
    """Nucleo do criterio de aceite: diferente de `latencia` (constante),
    o delay de degradacao_progressiva cresce conforme o tempo passa desde
    a ativacao - rampa de 0 ate ramp_ceiling_seconds ao longo de
    ramp_window_seconds."""
    monkeypatch.setattr(chaos_middleware.time, "monotonic", lambda: 1000.0)
    set_runtime_override(
        enabled=True,
        failure_rate=1.0,
        failure_types=["degradacao_progressiva"],
        duration_seconds=None,
        params=ChaosTypeParams(ramp_ceiling_seconds=10.0, ramp_window_seconds=100.0),
    )

    monkeypatch.setattr(chaos_middleware.time, "monotonic", lambda: 1000.0)
    assert chaos_middleware._degradacao_progressiva_delay_seconds() == 0.0

    monkeypatch.setattr(chaos_middleware.time, "monotonic", lambda: 1050.0)
    assert chaos_middleware._degradacao_progressiva_delay_seconds() == 5.0

    monkeypatch.setattr(chaos_middleware.time, "monotonic", lambda: 1100.0)
    assert chaos_middleware._degradacao_progressiva_delay_seconds() == 10.0

    # Depois da janela, fica no teto - nao ultrapassa nem volta a subir.
    monkeypatch.setattr(chaos_middleware.time, "monotonic", lambda: 5000.0)
    assert chaos_middleware._degradacao_progressiva_delay_seconds() == 10.0


def test_degradacao_progressiva_injection_delays_then_returns_real_response(monkeypatch):
    monkeypatch.setattr(chaos_middleware.random, "random", lambda: 0.0)
    monkeypatch.setattr(chaos_middleware.random, "choice", lambda choices: "degradacao_progressiva")
    monkeypatch.setattr(chaos_middleware.time, "monotonic", lambda: 1000.0)
    set_runtime_override(
        enabled=True,
        failure_rate=1.0,
        failure_types=["degradacao_progressiva"],
        duration_seconds=None,
        params=ChaosTypeParams(ramp_ceiling_seconds=3.0, ramp_window_seconds=60.0),
    )
    monkeypatch.setattr(chaos_middleware.time, "monotonic", lambda: 1030.0)
    sleep_calls = []

    async def _tracked_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(chaos_middleware.asyncio, "sleep", _tracked_sleep)
    client = TestClient(_build_app())

    response = client.get("/v1/widgets")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert sleep_calls == [1.5]


@pytest.mark.parametrize("failure_type", ["kafka_lag", "kafka_delay"])
def test_kafka_only_types_are_a_noop_for_http_requests(monkeypatch, failure_type, caplog):
    """kafka_lag/kafka_delay sao consultados direto pelo producer/consumer
    (chaos/kafka_chaos.py), nunca escolhidos de verdade para uma
    requisicao HTTP - mas se o sorteio cair num deles aqui (porque estao
    na mesma lista compartilhada de failure_types), a requisicao precisa
    passar batido, nunca virar um 500 generico por engano, e sem logar
    "chaos injetado" - nada foi de fato injetado nesta requisicao."""
    monkeypatch.setenv("CHAOS_ENABLED", "true")
    monkeypatch.setenv("CHAOS_FAILURE_RATE", "1.0")
    monkeypatch.setattr(chaos_middleware.random, "random", lambda: 0.0)
    monkeypatch.setattr(chaos_middleware.random, "choice", lambda choices: failure_type)
    client = TestClient(_build_app())

    with caplog.at_level(logging.WARNING, logger="chaos"):
        response = client.get("/v1/widgets")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert [r for r in caplog.records if r.name == "chaos"] == []
