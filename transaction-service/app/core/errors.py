import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_trace_id

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """Base para exceções de domínio mapeadas para uma resposta HTTP específica."""

    error_code: str = "DOMAIN_ERROR"
    status_code: int = 400
    field: str | None = None

    def __init__(self, message: str, field: str | None = None):
        super().__init__(message)
        self.message = message
        if field is not None:
            self.field = field


def _error_response(status_code: int, error_code: str, message: str, field: str | None, trace_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error_code,
            "message": message,
            "field": field,
            "trace_id": trace_id,
        },
    )


class AccountNotActiveError(DomainError):
    error_code = "ACCOUNT_NOT_ACTIVE"
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Conta de origem nao esta ativa.")


class PixKeyDestinoNotFoundError(DomainError):
    error_code = "PIX_KEY_DESTINO_NOT_FOUND"
    status_code = 404

    def __init__(self) -> None:
        super().__init__("Chave PIX de destino nao encontrada.")


class PixKeyDestinoInativaError(DomainError):
    error_code = "PIX_KEY_DESTINO_INATIVA"
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Chave PIX de destino foi cancelada.")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        return _error_response(exc.status_code, exc.error_code, exc.message, exc.field, get_trace_id())

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        field = None
        if errors:
            loc = errors[0].get("loc", ())
            field = str(loc[-1]) if loc else None
        return _error_response(400, "VALIDATION_ERROR", "Payload invalido.", field, get_trace_id())

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        trace_id = get_trace_id()
        logger.error(
            "Erro interno nao mapeado.",
            extra={"trace_id": trace_id, "context": {"stack_trace": traceback.format_exc()}},
        )
        return _error_response(500, "INTERNAL_ERROR", "Erro interno. Tente novamente.", None, trace_id)
