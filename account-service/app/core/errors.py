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


class OnboardingNotFoundError(DomainError):
    error_code = "ONBOARDING_NOT_FOUND"
    status_code = 404

    def __init__(self) -> None:
        super().__init__("Onboarding nao encontrado.")


class OnboardingNotApprovedError(DomainError):
    error_code = "ONBOARDING_NOT_APPROVED"
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Onboarding ainda nao foi aprovado.")


class AccountAlreadyExistsError(DomainError):
    error_code = "ACCOUNT_ALREADY_EXISTS"
    status_code = 409

    def __init__(self) -> None:
        super().__init__("Conta ja existe para este onboarding.")


class AccountNotFoundError(DomainError):
    error_code = "ACCOUNT_NOT_FOUND"
    status_code = 404

    def __init__(self) -> None:
        super().__init__("Conta nao encontrada.")


class SaldoInsuficienteError(DomainError):
    error_code = "SALDO_INSUFICIENTE"
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Saldo insuficiente para a transferencia.")


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
        context: dict = {"stack_trace": traceback.format_exc()}
        if getattr(exc, "chaos_injected", False):
            # Falha injetada pela camada de caos (specs/business/11-camada-caos.md)
            # propagou ate aqui de proposito, para exercitar este handler
            # real - marcado para o agente preditivo nao confundir com bug.
            context["chaos_injected"] = True
        logger.error(
            "Erro interno nao mapeado.",
            extra={"trace_id": trace_id, "context": context},
        )
        return _error_response(500, "INTERNAL_ERROR", "Erro interno. Tente novamente.", None, trace_id)
