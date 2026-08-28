from unittest.mock import patch

from agent_preditivo.bug_detection import (
    LIMIAR_LATENCIA_MULTIPLICADOR,
    LIMIAR_LOG_REPETIDO,
    LIMIAR_SATURACAO_POOL,
    LIMIAR_TAXA_ERRO,
    check_latencia,
    check_log_repetido,
    check_saturacao_pool,
    check_taxa_erro,
    detect_bugs_for_service,
)
from agent_preditivo.logs_client import LogEntry
from agent_preditivo.prometheus_client import GoldenSignals


def _signals(**overrides) -> GoldenSignals:
    base = dict(
        service="transaction-service",
        taxa_erro=0.0,
        latencia_p95_atual=0.1,
        latencia_mediana_historica=0.1,
        saturacao_pool=0.0,
    )
    base.update(overrides)
    return GoldenSignals(**base)


def test_check_taxa_erro_caminho_feliz() -> None:
    assert check_taxa_erro(_signals(taxa_erro=0.01)) is None


def test_check_taxa_erro_dispara_acima_do_limiar() -> None:
    signal = check_taxa_erro(_signals(taxa_erro=LIMIAR_TAXA_ERRO + 0.01))
    assert signal is not None
    assert signal.signal_type == "erro_alto"
    assert signal.service == "transaction-service"


def test_check_latencia_caminho_feliz() -> None:
    assert check_latencia(_signals(latencia_p95_atual=0.15, latencia_mediana_historica=0.1)) is None


def test_check_latencia_dispara_acima_do_multiplicador() -> None:
    signal = check_latencia(
        _signals(latencia_p95_atual=0.1 * LIMIAR_LATENCIA_MULTIPLICADOR + 0.01, latencia_mediana_historica=0.1)
    )
    assert signal is not None
    assert signal.signal_type == "latencia_alta"


def test_check_latencia_sem_trafego_nao_dispara() -> None:
    assert check_latencia(_signals(latencia_p95_atual=None, latencia_mediana_historica=None)) is None


def test_check_saturacao_pool_caminho_feliz() -> None:
    assert check_saturacao_pool(_signals(saturacao_pool=0.5)) is None


def test_check_saturacao_pool_dispara_acima_do_limiar() -> None:
    signal = check_saturacao_pool(_signals(saturacao_pool=LIMIAR_SATURACAO_POOL + 0.01))
    assert signal is not None
    assert signal.signal_type == "saturacao_pool"


def _log(level: str, message: str) -> LogEntry:
    return LogEntry(timestamp="", service_name="x", level=level, trace_id="", message=message, context={}, raw="")


def test_check_log_repetido_caminho_feliz_sem_repeticao() -> None:
    entries = [_log("ERROR", "falha A")]
    assert check_log_repetido("transaction-service", entries) is None


def test_check_log_repetido_dispara_com_repeticao_suficiente() -> None:
    entries = [_log("ERROR", "falha A") for _ in range(LIMIAR_LOG_REPETIDO)]
    signal = check_log_repetido("transaction-service", entries)
    assert signal is not None
    assert signal.signal_type == "log_critico_repetido"


def test_check_log_repetido_ignora_niveis_abaixo_de_error() -> None:
    entries = [_log("WARNING", "algo") for _ in range(10)]
    assert check_log_repetido("transaction-service", entries) is None


def test_detect_bugs_for_service_marca_chaos_ativo_em_todos_os_sinais() -> None:
    """Regressao critica (specs/business/21-filtro-caos-pipeline-agentes.md):
    o sinal continua sendo detectado normalmente com o caos ligado (isso e
    o design pretendido, docs/escopo-arquitetura.md v17), mas cada
    BugSignal precisa carregar chaos_ativo=True para a issue ser marcada."""
    with (
        patch(
            "agent_preditivo.bug_detection.fetch_golden_signals",
            return_value=_signals(taxa_erro=LIMIAR_TAXA_ERRO + 0.1),
        ),
        patch("agent_preditivo.bug_detection.fetch_logs", return_value=[]),
        patch("agent_preditivo.bug_detection.is_chaos_enabled", return_value=True),
    ):
        signals = detect_bugs_for_service("transaction-service")

    assert len(signals) == 1
    assert signals[0].chaos_ativo is True


def test_detect_bugs_for_service_chaos_desligado_nao_marca() -> None:
    with (
        patch(
            "agent_preditivo.bug_detection.fetch_golden_signals",
            return_value=_signals(taxa_erro=LIMIAR_TAXA_ERRO + 0.1),
        ),
        patch("agent_preditivo.bug_detection.fetch_logs", return_value=[]),
        patch("agent_preditivo.bug_detection.is_chaos_enabled", return_value=False),
    ):
        signals = detect_bugs_for_service("transaction-service")

    assert len(signals) == 1
    assert signals[0].chaos_ativo is False
