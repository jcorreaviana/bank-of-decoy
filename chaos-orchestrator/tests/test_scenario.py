"""Testes de parsing do cenario YAML (scenario.py) - issue #53."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from scenario import DEFAULT_SERVICE_URLS, ScenarioError, load_scenario

EXAMPLE_SCENARIO_PATH = Path(__file__).resolve().parent.parent / "scenarios" / "account_and_queue_cascade.yaml"


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "cenario.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_carrega_cenario_valido_completo(tmp_path):
    path = _write(
        tmp_path,
        """
        name: teste-cascata
        description: cenario de teste
        timeline:
          - service: account-service
            failure_types: [degradacao_progressiva]
            start_minute: 2
            duration_minutes: 5
            params:
              failure_rate: 1.0
              ramp_ceiling_seconds: 3.0
              ramp_window_seconds: 240
          - service: onboarding-service
            failure_types: [kafka_delay]
            start_minute: 3
            duration_minutes: 4
            params:
              kafka_delay_seconds: 4.0
        """,
    )

    scenario = load_scenario(path)

    assert scenario.name == "teste-cascata"
    assert scenario.description == "cenario de teste"
    assert len(scenario.steps) == 2

    first, second = scenario.steps
    assert first.service == "account-service"
    assert first.failure_types == ["degradacao_progressiva"]
    assert first.start_minute == 2.0
    assert first.duration_minutes == 5.0
    assert first.end_minute == 7.0
    assert first.params == {"failure_rate": 1.0, "ramp_ceiling_seconds": 3.0, "ramp_window_seconds": 240.0}

    assert second.service == "onboarding-service"
    assert second.end_minute == 7.0

    # Sem service_urls no YAML - usa os defaults (mesmas portas do docker-compose.yml).
    assert scenario.service_urls == DEFAULT_SERVICE_URLS


def test_carrega_o_cenario_de_exemplo_real_da_issue():
    """O arquivo scenarios/account_and_queue_cascade.yaml (item 3 da issue #53)
    precisa ser um cenario valido de verdade, nao so um exemplo ilustrativo."""
    scenario = load_scenario(EXAMPLE_SCENARIO_PATH)

    assert scenario.name == "account-and-queue-cascade"
    assert [s.service for s in scenario.steps] == ["account-service", "onboarding-service"]
    assert [s.failure_types for s in scenario.steps] == [["degradacao_progressiva"], ["kafka_delay"]]
    assert scenario.steps[0].start_minute == 2.0
    assert scenario.steps[1].start_minute == 3.0


def test_service_urls_customizado_sobrescreve_apenas_o_servico_informado(tmp_path):
    path = _write(
        tmp_path,
        """
        timeline:
          - service: account-service
            failure_types: [latencia]
            start_minute: 0
            duration_minutes: 1
        service_urls:
          account-service: http://custom-host:9999
        """,
    )

    scenario = load_scenario(path)

    assert scenario.service_urls["account-service"] == "http://custom-host:9999"
    assert scenario.service_urls["onboarding-service"] == DEFAULT_SERVICE_URLS["onboarding-service"]


@pytest.mark.parametrize(
    "content,trecho_esperado_no_erro",
    [
        ("timeline: []", "pelo menos um passo"),
        (
            """
            timeline:
              - failure_types: [latencia]
                start_minute: 0
                duration_minutes: 1
            """,
            "'service' obrigatorio",
        ),
        (
            """
            timeline:
              - service: account-service
                start_minute: 0
                duration_minutes: 1
            """,
            "'failure_types'",
        ),
        (
            """
            timeline:
              - service: account-service
                failure_types: [latencia]
                duration_minutes: 1
            """,
            "'start_minute'",
        ),
        (
            """
            timeline:
              - service: account-service
                failure_types: [latencia]
                start_minute: 0
                duration_minutes: -1
            """,
            "'duration_minutes'",
        ),
        (
            """
            timeline:
              - service: account-service
                failure_types: [degradacao_progressiva]
                start_minute: 0
                duration_minutes: 1
                params:
                  campo_que_nao_existe: 1
            """,
"chave.s. desconhecida.s.",
        ),
        (
            """
            timeline:
              - service: servico-fantasma
                failure_types: [latencia]
                start_minute: 0
                duration_minutes: 1
            """,
            "sem URL conhecida",
        ),
    ],
)
def test_rejeita_cenario_invalido(tmp_path, content, trecho_esperado_no_erro):
    path = _write(tmp_path, content)

    with pytest.raises(ScenarioError, match=trecho_esperado_no_erro):
        load_scenario(path)
