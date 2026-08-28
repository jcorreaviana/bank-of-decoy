import logging
from unittest.mock import patch

from agent_preditivo.opportunity_detection import _judge
from agent_preditivo.scenarios import ScenarioResult


def _scenario(**overrides) -> ScenarioResult:
    base = dict(
        name="cenario_teste",
        rule_query="regra de teste",
        observed_behavior="comportamento observado de teste",
        passed_baseline=None,
    )
    base.update(overrides)
    return ScenarioResult(**base)


def test_judge_retorna_gap_quando_llm_responde_gap() -> None:
    with (
        patch("agent_preditivo.opportunity_detection.search_specs", return_value=[{"file": "x.md", "section": "s", "text": "regra clara", "distance": 1.0}]),
        patch("agent_preditivo.opportunity_detection.chat", return_value="VEREDITO: GAP\nRACIONAL: viola a regra clara"),
    ):
        finding = _judge(_scenario())

    assert finding.veredito == "GAP"
    assert "viola" in finding.racional


def test_judge_retorna_sem_gap_quando_llm_responde_sem_gap() -> None:
    with (
        patch("agent_preditivo.opportunity_detection.search_specs", return_value=[]),
        patch("agent_preditivo.opportunity_detection.chat", return_value="VEREDITO: SEM_GAP\nRACIONAL: nenhuma regra encontrada"),
    ):
        finding = _judge(_scenario())

    assert finding.veredito == "SEM_GAP"


def test_judge_sem_regra_recuperada_ainda_chama_llm_com_contexto_vazio() -> None:
    with (
        patch("agent_preditivo.opportunity_detection.search_specs", return_value=[]) as mock_search,
        patch("agent_preditivo.opportunity_detection.chat", return_value="VEREDITO: SEM_GAP\nRACIONAL: sem contexto") as mock_chat,
    ):
        _judge(_scenario())

    mock_search.assert_called_once()
    assert "nenhum trecho de spec" in mock_chat.call_args[0][1].lower()


def test_judge_formato_inesperado_do_llm_cai_para_sem_gap() -> None:
    with (
        patch("agent_preditivo.opportunity_detection.search_specs", return_value=[]),
        patch("agent_preditivo.opportunity_detection.chat", return_value="resposta fora do formato esperado"),
    ):
        finding = _judge(_scenario())

    assert finding.veredito == "SEM_GAP"


def test_judge_loga_info_com_veredito_do_cenario(caplog) -> None:
    """Issue #33: classificacao de cada cenario (GAP ou SEM_GAP) precisa
    ficar visivel no log, nao so no retorno do dataclass."""
    with (
        caplog.at_level(logging.INFO, logger="agent_preditivo.opportunity_detection"),
        patch("agent_preditivo.opportunity_detection.search_specs", return_value=[]),
        patch("agent_preditivo.opportunity_detection.chat", return_value="VEREDITO: SEM_GAP\nRACIONAL: nenhuma regra"),
    ):
        _judge(_scenario())

    messages = [record.message for record in caplog.records]
    assert any("avaliado" in m for m in messages)
