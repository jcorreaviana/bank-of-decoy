import time
from typing import Optional

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from sqlalchemy.engine import Engine
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

registry = CollectorRegistry()

http_requests_total = Counter(
    "http_requests_total",
    "Total de requisicoes HTTP recebidas.",
    ["route", "method", "status_code"],
    registry=registry,
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "Duracao das requisicoes HTTP em segundos.",
    ["route", "method"],
    registry=registry,
)

db_pool_connections_in_use = Gauge(
    "db_pool_connections_in_use",
    "Conexoes do pool de banco atualmente em uso.",
    registry=registry,
)

# Metricas de negocio (dashboard v1, specs/business/15-metricas-negocio.md).
transacao_processada_total = Counter(
    "transacao_processada_total",
    "Total de transferencias PIX processadas, por status.",
    ["status"],
    registry=registry,
)

_VALOR_REAIS_BUCKETS = (10, 50, 100, 500, 1_000, 5_000, 10_000, 20_000, 50_000)
"""Faixas em reais (nao os buckets default do Histogram, pensados para
duracao em segundos) - cobre desde transacoes pequenas ate acima do
limiar de valor atipico (VALOR_ATIPICO_LIMIAR=20_000, transaction_risk.py),
para o histograma mostrar onde a distribuicao real de valor cai."""

transacao_valor_reais = Histogram(
    "transacao_valor_reais",
    "Distribuicao do valor (R$) das transferencias PIX processadas.",
    buckets=_VALOR_REAIS_BUCKETS,
    registry=registry,
)

risco_sinal_total = Counter(
    "risco_sinal_total",
    "Total de ocorrencias de cada sinal de risco (onboarding e transacao - "
    "mesmo nome de metrica no onboarding-service, o label `job` do "
    "Prometheus distingue a origem).",
    ["sinal"],
    registry=registry,
)


def register_db_pool_gauge(engine: Optional[Engine]) -> None:
    if engine is None:
        return
    db_pool_connections_in_use.set_function(lambda: engine.pool.checkedout())


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        status_code = "500"
        try:
            response = await call_next(request)
            status_code = str(response.status_code)
            return response
        finally:
            duration = time.perf_counter() - start
            route = request.scope.get("route")
            route_path = route.path if route is not None else request.url.path
            method = request.method

            http_requests_total.labels(route=route_path, method=method, status_code=status_code).inc()
            http_request_duration_seconds.labels(route=route_path, method=method).observe(duration)
