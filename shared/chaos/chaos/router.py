"""Endpoint interno `POST /internal/chaos/config` (issue #51,
specs/business/24-camada-caos-avancada.md) - ajusta tipo(s) de falha
ativos, taxa (`CHAOS_FAILURE_RATE`) e duracao/janela da camada de caos
em runtime, sem restart do processo. Reaproveita a logica de injecao ja
existente em chaos/middleware.py: so troca a fonte de configuracao lida
em `_load_config()` (env var -> override em chaos/runtime_config.py).

Protegido por segredo compartilhado (chaos/internal_auth.py) em vez de
depender de isolamento de rede - ver docstring daquele modulo.

Uso em cada servico (app/main.py), mesmo padrao ja usado para
`register_exception_handlers(app)`/`register_db_pool_gauge(engine)`:

    from chaos import register_chaos_router
    ...
    register_chaos_router(app)
"""

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from chaos.internal_auth import is_internal_request_authorized
from chaos.known_types import KNOWN_FAILURE_TYPES
from chaos.runtime_config import ChaosRuntimeOverride, set_runtime_override

router = APIRouter()


class ChaosConfigForbiddenError(Exception):
    """Levantada pela dependency de autenticacao abaixo quando o header
    interno esperado nao bate - handler registrado em
    register_chaos_router(), no formato padrao de erro
    (specs/tech/error-handling.md)."""


def require_internal_token(request: Request) -> None:
    if not is_internal_request_authorized(request):
        raise ChaosConfigForbiddenError()


class ChaosConfigRequest(BaseModel):
    enabled: bool = True
    failure_rate: float = Field(default=0.05, ge=0.0, le=1.0)
    failure_types: list[str] = Field(default_factory=list)
    # Janela de validade do override, em segundos. `None` = sem
    # expiracao automatica (vale ate o proximo POST ou restart do
    # processo).
    duration_seconds: float | None = Field(default=None, gt=0)

    @field_validator("failure_types")
    @classmethod
    def _only_known_types(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - KNOWN_FAILURE_TYPES)
        if unknown:
            raise ValueError(f"tipo(s) de falha desconhecido(s): {', '.join(unknown)}")
        return value


class ChaosConfigResponse(BaseModel):
    enabled: bool
    failure_rate: float
    failure_types: list[str]
    expires_at: float | None


@router.post(
    "/internal/chaos/config",
    response_model=ChaosConfigResponse,
    dependencies=[Depends(require_internal_token)],
)
def post_chaos_config(payload: ChaosConfigRequest) -> ChaosConfigResponse:
    failure_types = payload.failure_types or list(KNOWN_FAILURE_TYPES)
    override: ChaosRuntimeOverride = set_runtime_override(
        enabled=payload.enabled,
        failure_rate=payload.failure_rate,
        failure_types=failure_types,
        duration_seconds=payload.duration_seconds,
    )
    return ChaosConfigResponse(
        enabled=override.enabled,
        failure_rate=override.failure_rate,
        failure_types=override.failure_types,
        expires_at=override.expires_at,
    )


def register_chaos_router(app: FastAPI) -> None:
    """Registra o router acima e o exception handler do erro de
    autorizacao num unico passo, para os 4 servicos nao precisarem
    duplicar o registro do handler."""

    @app.exception_handler(ChaosConfigForbiddenError)
    async def _chaos_config_forbidden_handler(request: Request, exc: ChaosConfigForbiddenError) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={
                "error_code": "CHAOS_CONFIG_FORBIDDEN",
                "message": "Acesso negado ao endpoint interno de configuracao de caos.",
                "field": None,
                "trace_id": request.headers.get("X-Trace-Id"),
            },
        )

    app.include_router(router)
