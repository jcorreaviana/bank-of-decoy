"""Cliente REST sincrono para o account-service (GET /v1/accounts/{id}),
usado para validar que a conta de origem esta "ativa" antes de criar uma
transacao (specs/business/06-pixkey-transaction-crud.md).

Versao provisoria e sincrona, mesma filosofia do account-service ->
onboarding-service (issue #5, app/services/onboarding_internal_client.py em
account-service): sem retry/circuit breaker sofisticado, uma falha aqui deve
ficar visivel (log + erro), nao escondida atras de tentativas automaticas.
Sera substituida pelo fluxo de eventos Kafka em fase futura.
"""

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_TIMEOUT_SECONDS = 5.0


class AccountNotFoundUpstreamError(Exception):
    """O account-service respondeu 404 - account_id inexistente ou deletado."""


class AccountServiceUnavailableError(Exception):
    """Falha na chamada sincrona ao account-service (timeout, conexao
    recusada, resposta inesperada)."""


def fetch_account(account_id: str, trace_id: str = "") -> dict:
    settings = get_settings()
    url = f"{settings.account_service_url}/v1/accounts/{account_id}"
    headers = {"X-Trace-Id": trace_id} if trace_id else {}

    try:
        response = httpx.get(url, headers=headers, timeout=_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        logger.error(
            "Falha na chamada sincrona ao account-service.",
            extra={"context": {"target_url": url, "account_id": account_id, "error": str(exc)}},
        )
        raise AccountServiceUnavailableError("account-service indisponivel") from exc

    if response.status_code == 404:
        raise AccountNotFoundUpstreamError()

    if response.status_code >= 400:
        logger.error(
            "Resposta inesperada do account-service.",
            extra={
                "context": {
                    "target_url": url,
                    "account_id": account_id,
                    "status_code": response.status_code,
                }
            },
        )
        raise AccountServiceUnavailableError("account-service retornou erro inesperado")

    return response.json()
