"""Testes do motor da timeline (orchestrator.py) - issue #53.

Usa uma FakeClock que avanca instantaneamente (sem esperar minutos reais,
requisito explicito da issue) e um post_fn fake que so registra as chamadas,
sem rede de verdade."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import pytest

from orchestrator import Clock, Orchestrator, SAFETY_MARGIN_SECONDS
from scenario import Scenario, TimelineStep


class FakeClock(Clock):
    """Relogio virtual: `sleep_until` pula direto para o alvo em vez de
    esperar, `sleep` avanca o relogio pelo numero de segundos pedido."""

    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self.t += seconds

    def sleep_until(self, target: float, *, should_stop) -> None:
        if should_stop():
            return
        if target > self.t:
            self.t = target


def _recording_post_fn(calls: list):
    def post_fn(base_url: str, payload: dict, *, token: str) -> dict:
        assert token == "token-de-teste"
        calls.append((base_url, dict(payload)))
        return {}

    return post_fn


def _scenario(steps: list[TimelineStep]) -> Scenario:
    return Scenario(
        name="cenario-teste",
        description="",
        steps=steps,
        service_urls={
            "account-service": "http://account",
            "onboarding-service": "http://onboarding",
        },
    )


def test_executa_timeline_chamando_servico_certo_no_minuto_certo():
    steps = [
        TimelineStep(
            service="account-service",
            failure_types=["degradacao_progressiva"],
            start_minute=2,
            duration_minutes=5,
            params={"failure_rate": 1.0, "ramp_ceiling_seconds": 3.0, "ramp_window_seconds": 240},
        ),
        TimelineStep(
            service="onboarding-service",
            failure_types=["kafka_delay"],
            start_minute=3,
            duration_minutes=4,
            params={"kafka_delay_seconds": 4.0},
        ),
    ]
    calls: list = []
    orchestrator = Orchestrator(
        _scenario(steps),
        token="token-de-teste",
        post_fn=_recording_post_fn(calls),
        clock=FakeClock(),
    )

    orchestrator.run()

    # 2 ativacoes + 2 desligamentos, nesta ordem (a timeline e cronologica:
    # ativa account em t=2, ativa onboarding em t=3, desliga account em t=7,
    # desliga onboarding em t=7 - mesmo minuto, mas onboarding comecou depois).
    assert len(calls) == 4

    account_activate = calls[0]
    assert account_activate[0] == "http://account"
    assert account_activate[1]["enabled"] is True
    assert account_activate[1]["failure_types"] == ["degradacao_progressiva"]
    assert account_activate[1]["ramp_ceiling_seconds"] == 3.0
    # duration_seconds = (7 - 2) minutos restantes * 60 + margem de seguranca
    assert account_activate[1]["duration_seconds"] == pytest.approx(5 * 60 + SAFETY_MARGIN_SECONDS)

    onboarding_activate = calls[1]
    assert onboarding_activate[0] == "http://onboarding"
    assert onboarding_activate[1]["failure_types"] == ["kafka_delay"]
    assert onboarding_activate[1]["kafka_delay_seconds"] == 4.0
    assert onboarding_activate[1]["duration_seconds"] == pytest.approx(4 * 60 + SAFETY_MARGIN_SECONDS)

    account_deactivate, onboarding_deactivate = calls[2], calls[3]
    assert account_deactivate == ("http://account", {"enabled": False})
    assert onboarding_deactivate == ("http://onboarding", {"enabled": False})


def test_ativacoes_sobrepostas_no_mesmo_servico_se_fundem_em_vez_de_se_substituir():
    """Sem a fusao, a segunda ativacao (kafka_lag) apagaria a primeira
    (degradacao_progressiva) no mesmo servico - ver runtime_config.py:
    cada POST substitui failure_types por completo."""
    steps = [
        TimelineStep(
            service="account-service",
            failure_types=["degradacao_progressiva"],
            start_minute=0,
            duration_minutes=4,
            params={"ramp_ceiling_seconds": 2.0},
        ),
        TimelineStep(
            service="account-service",
            failure_types=["kafka_lag"],
            start_minute=2,
            duration_minutes=2,
            params={"lag_increment_ms": 300.0},
        ),
    ]
    calls: list = []
    orchestrator = Orchestrator(
        _scenario(steps),
        token="token-de-teste",
        post_fn=_recording_post_fn(calls),
        clock=FakeClock(),
    )

    orchestrator.run()

    assert len(calls) == 4

    first_activate = calls[0][1]
    assert first_activate["failure_types"] == ["degradacao_progressiva"]

    second_activate = calls[1][1]
    # No minuto 2, o segundo passo ainda tem o primeiro ativo (termina no
    # minuto 4) - a chamada precisa incluir OS DOIS tipos, senao o segundo
    # POST desligaria degradacao_progressiva sem querer.
    assert second_activate["failure_types"] == ["degradacao_progressiva", "kafka_lag"]
    assert second_activate["ramp_ceiling_seconds"] == 2.0
    assert second_activate["lag_increment_ms"] == 300.0

    # Os dois passos terminam no minuto 4 - o primeiro a desligar (evento
    # inserido primeiro na timeline) so remove seu proprio tipo, mantendo
    # kafka_lag ativo; so o segundo desligamento zera o servico de vez.
    partial_deactivate = calls[2][1]
    assert partial_deactivate["enabled"] is True
    assert partial_deactivate["failure_types"] == ["kafka_lag"]

    full_deactivate = calls[3][1]
    assert full_deactivate == {"enabled": False}


def test_falha_de_rede_num_passo_e_logada_mas_nao_derruba_os_proximos():
    steps = [
        TimelineStep(service="account-service", failure_types=["latencia"], start_minute=0, duration_minutes=1),
        TimelineStep(service="onboarding-service", failure_types=["kafka_delay"], start_minute=1, duration_minutes=1),
    ]
    calls: list = []

    def flaky_post_fn(base_url: str, payload: dict, *, token: str) -> dict:
        if base_url == "http://account" and payload.get("enabled") is True:
            raise httpx.ConnectTimeout("timeout simulado")
        calls.append((base_url, dict(payload)))
        return {}

    logs: list = []

    def recording_log(level, message, *, trace_id, context=None):
        logs.append({"level": level, "message": message, "context": context or {}})

    orchestrator = Orchestrator(
        _scenario(steps),
        token="token-de-teste",
        post_fn=flaky_post_fn,
        clock=FakeClock(),
        log_fn=recording_log,
    )

    orchestrator.run()

    error_logs = [entry for entry in logs if entry["level"] == "ERROR"]
    assert len(error_logs) == 1
    assert "account-service" in error_logs[0]["message"]

    # A ativacao de account-service falhou (nunca chega a "calls"), mas o
    # passo seguinte (onboarding-service) roda normalmente.
    onboarding_calls = [c for c in calls if c[0] == "http://onboarding"]
    assert len(onboarding_calls) == 2  # ativa e desliga, normalmente
    assert onboarding_calls[0][1]["enabled"] is True
    assert onboarding_calls[1][1] == {"enabled": False}


def test_interrupcao_antes_do_fim_natural_desliga_o_que_estiver_ativo():
    step = TimelineStep(service="account-service", failure_types=["degradacao_progressiva"], start_minute=0, duration_minutes=10)
    calls: list = []
    orchestrator_holder = {}

    def post_fn(base_url: str, payload: dict, *, token: str) -> dict:
        calls.append((base_url, dict(payload)))
        if payload.get("enabled") is True:
            # Simula o SIGINT chegando logo depois da ativacao, antes do
            # desligamento natural (previsto so no minuto 10).
            orchestrator_holder["orchestrator"].request_stop()
        return {}

    orchestrator = Orchestrator(
        _scenario([step]),
        token="token-de-teste",
        post_fn=post_fn,
        clock=FakeClock(),
    )
    orchestrator_holder["orchestrator"] = orchestrator

    orchestrator.run()

    assert len(calls) == 2
    assert calls[0][1]["enabled"] is True
    assert calls[1] == ("http://account", {"enabled": False})


def test_fim_natural_da_timeline_nao_gera_desligamento_extra():
    """_shutdown_all() precisa ser um no-op quando a timeline terminou
    normalmente - cada passo ja desligou a si mesmo."""
    step = TimelineStep(service="account-service", failure_types=["latencia"], start_minute=0, duration_minutes=1)
    calls: list = []
    orchestrator = Orchestrator(
        _scenario([step]),
        token="token-de-teste",
        post_fn=_recording_post_fn(calls),
        clock=FakeClock(),
    )

    orchestrator.run()

    assert len(calls) == 2
    assert calls[1][1] == {"enabled": False}
