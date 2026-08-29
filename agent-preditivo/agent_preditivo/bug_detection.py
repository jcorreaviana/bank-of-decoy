"""Aplica os 4 thresholds do agente de bug ja definidos em
docs/escopo-arquitetura.md e specs/business/13-agente-preditivo-registro.md:

- taxa de erro > 5% em 5 min por servico
- latencia p95 > 2x mediana historica
- saturacao de pool de conexao > 80%
- log CRITICAL/ERROR repetido 3+ vezes em 5 min com a mesma mensagem
"""

import logging
from dataclasses import dataclass, replace

from agent_preditivo.chaos_status import is_chaos_enabled
from agent_preditivo.logs_client import LogEntry, count_repeated_critical_or_error, fetch_logs
from agent_preditivo.prometheus_client import GoldenSignals, fetch_golden_signals

logger = logging.getLogger(__name__)

LIMIAR_TAXA_ERRO = 0.05
LIMIAR_LATENCIA_MULTIPLICADOR = 2.0
LIMIAR_SATURACAO_POOL = 0.80
LIMIAR_LOG_REPETIDO = 3


@dataclass(frozen=True)
class BugSignal:
    service: str
    signal_type: str
    """erro_alto | latencia_alta | saturacao_pool | log_critico_repetido."""
    detail: str
    chaos_ativo: bool = False
    """True se CHAOS_ENABLED estava ativo no servico no momento da deteccao
    (specs/business/21-filtro-caos-pipeline-agentes.md) - o sinal ainda e
    reportado normalmente (o design pretendido, docs/escopo-arquitetura.md
    v17, e que o caos dispare os thresholds do agente de bug como teste de
    ponta a ponta), mas a issue criada a partir dele precisa deixar claro
    que a causa e falha simulada, nao bug de codigo."""


def check_taxa_erro(signals: GoldenSignals) -> BugSignal | None:
    if signals.taxa_erro > LIMIAR_TAXA_ERRO:
        return BugSignal(
            service=signals.service,
            signal_type="erro_alto",
            detail=f"taxa de erro {signals.taxa_erro:.2%} > {LIMIAR_TAXA_ERRO:.0%} em 5 min",
        )
    return None


def check_latencia(signals: GoldenSignals) -> BugSignal | None:
    if signals.latencia_p95_atual is None or not signals.latencia_mediana_historica:
        return None
    if signals.latencia_p95_atual > signals.latencia_mediana_historica * LIMIAR_LATENCIA_MULTIPLICADOR:
        return BugSignal(
            service=signals.service,
            signal_type="latencia_alta",
            detail=(
                f"p95 atual {signals.latencia_p95_atual:.3f}s > "
                f"{LIMIAR_LATENCIA_MULTIPLICADOR}x a mediana historica "
                f"({signals.latencia_mediana_historica:.3f}s)"
            ),
        )
    return None


def check_saturacao_pool(signals: GoldenSignals) -> BugSignal | None:
    if signals.saturacao_pool > LIMIAR_SATURACAO_POOL:
        return BugSignal(
            service=signals.service,
            signal_type="saturacao_pool",
            detail=f"saturacao de pool {signals.saturacao_pool:.0%} > {LIMIAR_SATURACAO_POOL:.0%}",
        )
    return None


def check_log_repetido(service: str, entries: list[LogEntry]) -> BugSignal | None:
    counts = count_repeated_critical_or_error(entries)
    for key, count in counts.items():
        if count >= LIMIAR_LOG_REPETIDO:
            return BugSignal(
                service=service,
                signal_type="log_critico_repetido",
                detail=f"'{key}' repetido {count}x em 5 min",
            )
    return None


def detect_bugs_for_service(
    service: str, prometheus_url: str | None = None, base_url: str | None = None
) -> list[BugSignal]:
    signals = fetch_golden_signals(service, prometheus_url=prometheus_url)
    entries = fetch_logs(service, since="5m")
    logger.info(
        "Golden signals e logs estruturados consultados.",
        extra={
            "context": {
                "service": service,
                "taxa_erro": signals.taxa_erro,
                "latencia_p95_atual": signals.latencia_p95_atual,
                "latencia_mediana_historica": signals.latencia_mediana_historica,
                "saturacao_pool": signals.saturacao_pool,
                "log_entries_5m": len(entries),
            }
        },
    )

    found = [
        check_taxa_erro(signals),
        check_latencia(signals),
        check_saturacao_pool(signals),
        check_log_repetido(service, entries),
    ]
    chaos_ativo = is_chaos_enabled(service, base_url)
    result = [replace(signal, chaos_ativo=chaos_ativo) for signal in found if signal is not None]

    if result:
        for signal in result:
            logger.info(
                "Sinal de bug detectado.",
                extra={
                    "context": {
                        "service": signal.service,
                        "signal_type": signal.signal_type,
                        "detail": signal.detail,
                        "chaos_ativo": signal.chaos_ativo,
                    }
                },
            )
    else:
        logger.info(
            "Nenhum sinal de bug detectado neste ciclo.",
            extra={"context": {"service": service}},
        )
    return result
