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


def register_db_pool_gauge(engine: Optional[Engine]) -> None:
    if engine is None:
        return
    db_pool_connections_in_use.set_function(lambda: engine.pool.checkedout())


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        route = request.scope.get("route")
        route_path = route.path if route is not None else request.url.path
        method = request.method
        status_code = str(response.status_code)

        http_requests_total.labels(route=route_path, method=method, status_code=status_code).inc()
        http_request_duration_seconds.labels(route=route_path, method=method).observe(duration)

        return response
