"""Cliente para os golden signals expostos via Prometheus (issue #9,
specs/tech/observability.md), consultados via API HTTP de instant query
(`/api/v1/query`) - nenhuma dependencia externa alem de httpx.

Metricas disponiveis (onboarding-service/app/core/metrics.py e equivalentes
nos outros 3 servicos):
- http_requests_total{route,method,status_code} (counter)
- http_request_duration_seconds{route,method} (histogram)
- db_pool_connections_in_use (gauge, sem metrica de tamanho do pool - o
  tamanho e o default do SQLAlchemy, POOL_SIZE_PADRAO abaixo, decisao
  documentada por nao haver metrica dedicada)
"""

from dataclasses import dataclass

import httpx

from agent_preditivo.config import get_settings

_TIMEOUT_SECONDS = 10.0

POOL_SIZE_PADRAO = 5
"""Nenhum servico configura `pool_size` explicito em `create_engine`
(app/core/db.py) - o SQLAlchemy usa o default (5). Sem metrica de tamanho
de pool exposta, a saturacao e calculada contra essa constante."""


@dataclass(frozen=True)
class GoldenSignals:
    service: str
    taxa_erro: float
    """Fracao de requisicoes 5xx sobre o total, na janela de 5 min (0.0-1.0)."""
    latencia_p95_atual: float | None
    """p95 de latencia (segundos) na janela de 5 min. None se sem trafego."""
    latencia_mediana_historica: float | None
    """Mediana de latencia (segundos) na janela de 1h, usada como baseline
    "historica" (specs/business/13-agente-preditivo-registro.md nao define
    o tamanho da janela historica - 1h documentado aqui como decisao)."""
    saturacao_pool: float
    """Fracao de conexoes em uso sobre POOL_SIZE_PADRAO (0.0-1.0+)."""


def _instant_query(prometheus_url: str, promql: str) -> float | None:
    response = httpx.get(
        f"{prometheus_url}/api/v1/query", params={"query": promql}, timeout=_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    result = response.json()["data"]["result"]
    if not result:
        return None
    value = result[0]["value"][1]
    return float(value)


def fetch_golden_signals(service: str, prometheus_url: str | None = None) -> GoldenSignals:
    prometheus_url = prometheus_url or get_settings().prometheus_url

    total_5m = _instant_query(prometheus_url, f'sum(rate(http_requests_total{{job="{service}"}}[5m]))')
    erros_5m = _instant_query(
        prometheus_url, f'sum(rate(http_requests_total{{job="{service}",status_code=~"5.."}}[5m]))'
    )
    taxa_erro = ((erros_5m or 0.0) / total_5m) if total_5m else 0.0

    p95_atual = _instant_query(
        prometheus_url,
        f'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{{job="{service}"}}[5m])) by (le))',
    )
    mediana_historica = _instant_query(
        prometheus_url,
        f'histogram_quantile(0.5, sum(rate(http_request_duration_seconds_bucket{{job="{service}"}}[1h])) by (le))',
    )

    pool_em_uso = _instant_query(prometheus_url, f'db_pool_connections_in_use{{job="{service}"}}') or 0.0
    saturacao_pool = pool_em_uso / POOL_SIZE_PADRAO

    return GoldenSignals(
        service=service,
        taxa_erro=taxa_erro,
        latencia_p95_atual=p95_atual,
        latencia_mediana_historica=mediana_historica,
        saturacao_pool=saturacao_pool,
    )
