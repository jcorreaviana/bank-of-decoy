"""Middleware de injecao de falhas simuladas (camada de caos, Fase 2 -
specs/business/11-camada-caos.md). Compartilhado entre os 4 microservicos,
mesmo padrao de dependencia local editable ja usado por shared/test_safety
e shared/risk_engine.

Cada servico liga e configura o caos de forma independente, via variaveis
de ambiente proprias (CHAOS_ENABLED, CHAOS_FAILURE_RATE,
CHAOS_FAILURE_TYPES) - nao ha estado ou coordenacao compartilhada entre
servicos.

Desde a issue #51 (specs/business/24-camada-caos-avancada.md), essas
variaveis de ambiente passam a ser apenas a config inicial/fallback:
`POST /internal/chaos/config` (chaos/router.py) permite sobrepor os
mesmos 3 parametros em runtime, sem restart - ver chaos/runtime_config.py.

Ordem de registro: este middleware precisa ser adicionado ANTES de
RequestLoggingMiddleware/MetricsMiddleware (ou seja, a primeira chamada
`app.add_middleware(...)` de cada servico). O Starlette empacota middlewares
com o ULTIMO `add_middleware` como camada mais externa - registrar o caos
primeiro garante que ele fica na camada mais interna, entao (1) o trace_id
ja foi atribuido quando o caos loga o evento e (2) o MetricsMiddleware
continua contando/medindo as falhas injetadas (senao o dashboard Grafana
nunca mostraria efeito nenhum ao ligar o caos).
"""

import asyncio
import logging
import random
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Match

from chaos.payload_corruption import maybe_corrupt_response
from chaos.runtime_config import get_activation_time, get_active_type_params, get_effective_config

logger = logging.getLogger("chaos")

# /health e /metrics ficam de fora do sorteio: se o caos derrubasse o
# healthcheck do compose ou o endpoint que o Prometheus faz scrape, o
# proprio mecanismo de observabilidade usado para VALIDAR o caos ficaria
# cego (specs/business/11-camada-caos.md exige efeito visivel no Grafana).
# /internal/chaos/config tambem fica de fora: senao o proprio endpoint
# usado para desligar/ajustar o caos poderia ser vitima dele (issue #51).
# /internal/chaos/status (issue #57) pelo mesmo motivo: precisa responder
# de forma confiavel mesmo com o caos ativo - e exatamente quando o
# agent-preditivo mais precisa perguntar "esta ativo?".
_EXEMPT_PATHS = {"/health", "/metrics", "/internal/chaos/config", "/internal/chaos/status"}

# Duracoes fixas, nao expostas como variavel de ambiente adicional - a
# spec de negocio define apenas os 3 env vars acima como superficie de
# configuracao. `timeout` precisa exceder o timeout sincrono usado entre
# servicos internos (5s, ver transaction-service/app/services/account_client.py
# e account-service/app/services/onboarding_internal_client.py) para de
# fato estourar o timeout de quem chama.
_TIMEOUT_DELAY_SECONDS = 10.0
_LATENCY_DELAY_SECONDS = 2.0


class ChaosInjectedError(RuntimeError):
    """Excecao propositalmente nao tratada (failure_type "500") - precisa
    propagar sem ser capturada aqui, para exercitar o exception handler
    global real de cada servico (specs/tech/error-handling.md) em vez de
    simular a resposta diretamente no middleware de caos."""

    chaos_injected = True

    def __init__(self) -> None:
        super().__init__("Falha simulada pela camada de caos (500 nao tratado).")


def _iter_leaf_routes(routes):
    """FastAPI >=0.14x agrupa rotas incluidas via `include_router` em
    wrappers internos (`_IncludedRouter`/`_EffectiveRouteContext`, nao
    documentados publicamente) em vez da lista plana de `APIRoute` que
    versoes mais antigas do Starlette expunham direto em
    `router.routes`. Descer via duck-typing (`effective_candidates`,
    presente nesses wrappers) em vez de checar o tipo/nome exato mantem
    isso resiliente a mudanca de implementacao interna entre versoes."""
    for route in routes:
        if hasattr(route, "effective_candidates"):
            yield from _iter_leaf_routes(route.effective_candidates())
        else:
            yield route


def _assign_route_template(request: Request) -> None:
    """Preenche `request.scope["route"]` manualmente antes de um
    curto-circuito (503/500/timeout nunca chamam `call_next`, entao o
    Router nunca roda para atribuir isso sozinho). Sem isso,
    MetricsMiddleware cai no path com valores reais interpolados (ex. UUID
    da conta) em vez do path template - explode cardinalidade das metricas
    (specs/tech/observability.md)."""
    if request.scope.get("route") is not None:
        return
    for route in _iter_leaf_routes(request.app.router.routes):
        match, _ = route.matches(request.scope)
        if match == Match.FULL:
            request.scope["route"] = route
            return


def _degradacao_progressiva_delay_seconds() -> float:
    """Rampa de 0 ate ramp_ceiling_seconds ao longo de
    ramp_window_seconds, contados desde a ativacao (chaos/runtime_config.py
    - reinicia a cada POST /internal/chaos/config). Diferente de
    `latencia` (delay constante), aqui o delay cresce com o tempo -
    testa deteccao de tendencia no golden signal, nao so limiar
    (specs/business/24-camada-caos-avancada.md)."""
    params = get_active_type_params()
    if params.ramp_window_seconds <= 0:
        return params.ramp_ceiling_seconds
    elapsed = time.monotonic() - get_activation_time()
    progress = min(max(elapsed, 0.0) / params.ramp_window_seconds, 1.0)
    return progress * params.ramp_ceiling_seconds


def _load_config() -> tuple[bool, float, list[str]]:
    # Wrapper fino sobre chaos.runtime_config.get_effective_config() -
    # extraida de la (issue #57) para GET /internal/chaos/status
    # (chaos/router.py) usar exatamente a mesma logica, sem risco de
    # divergir do que este middleware realmente injeta.
    return get_effective_config()


class ChaosMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        enabled, failure_rate, failure_types = _load_config()

        if not enabled or request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        if random.random() >= failure_rate:
            return await call_next(request)

        failure_type = random.choice(failure_types)

        if failure_type in ("kafka_lag", "kafka_delay"):
            # Tipos exclusivos dos pontos de integracao Kafka
            # (chaos/kafka_chaos.py, consultado direto pelo producer/
            # consumer) - nao fazem sentido para uma requisicao HTTP
            # generica escolhida aqui. Sai ANTES do log abaixo: nada foi
            # de fato injetado nesta requisicao, entao logar
            # "chaos_injected" aqui seria enganoso.
            return await call_next(request)

        trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())

        logger.warning(
            "Falha simulada injetada pela camada de caos.",
            extra={
                "trace_id": trace_id,
                "context": {
                    "chaos_injected": True,
                    "failure_type": failure_type,
                    "route": request.url.path,
                    "method": request.method,
                },
            },
        )

        if failure_type == "503":
            _assign_route_template(request)
            return JSONResponse(
                status_code=503,
                content={
                    "error_code": "CHAOS_SERVICE_UNAVAILABLE",
                    "message": "Servico indisponivel (falha simulada pela camada de caos).",
                    "field": None,
                    "trace_id": trace_id,
                },
            )

        if failure_type == "latencia":
            await asyncio.sleep(_LATENCY_DELAY_SECONDS)
            return await call_next(request)

        if failure_type == "timeout":
            await asyncio.sleep(_TIMEOUT_DELAY_SECONDS)
            _assign_route_template(request)
            return JSONResponse(
                status_code=504,
                content={
                    "error_code": "CHAOS_TIMEOUT_INJECTED",
                    "message": "Tempo de resposta excedido (falha simulada pela camada de caos).",
                    "field": None,
                    "trace_id": trace_id,
                },
            )

        if failure_type == "degradacao_progressiva":
            await asyncio.sleep(_degradacao_progressiva_delay_seconds())
            return await call_next(request)

        if failure_type == "payload_corrompido_sutil":
            response = await call_next(request)
            # FastAPI atribui request.scope["route"] sozinho ao rotear de
            # verdade (fastapi/routing.py), mas isso nao e garantia da
            # ASGI spec nem do Starlette puro - mesmo fallback defensivo
            # ja usado nos curto-circuitos acima, agora depois do
            # call_next em vez de antes.
            _assign_route_template(request)
            return await maybe_corrupt_response(request, response)

        # failure_type == "500"
        _assign_route_template(request)
        raise ChaosInjectedError()
