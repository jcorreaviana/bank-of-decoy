"""Cliente REST sincrono para o account-service (POST /v1/accounts/transferencias),
usado para debitar a conta de origem e creditar a conta de destino ANTES de
criar as duas linhas do ledger de partida dobrada
(specs/business/16-saldo-partida-dobrada.md).

account-service e a fonte da verdade do saldo (decisao de arquitetura: o
dominio da conta decide se ela pode gastar, a transacao so e uma
interessada). Mesma filosofia sincrona/sem-retry de app/services/account_client.py.
"""

import uuid

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_TIMEOUT_SECONDS = 5.0


class SaldoInsuficienteUpstreamError(Exception):
    """O account-service respondeu 422 SALDO_INSUFICIENTE."""


class AccountTransferServiceUnavailableError(Exception):
    """Falha na chamada sincrona ao account-service (timeout, conexao
    recusada, resposta inesperada)."""


def transferir_saldo(
    conta_origem_id: uuid.UUID, conta_destino_id: uuid.UUID, valor: float, trace_id: str = ""
) -> dict:
    settings = get_settings()
    url = f"{settings.account_service_url}/v1/accounts/transferencias"
    headers = {"X-Trace-Id": trace_id} if trace_id else {}
    payload = {
        "conta_origem_id": str(conta_origem_id),
        "conta_destino_id": str(conta_destino_id),
        "valor": valor,
    }

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        logger.error(
            "Falha na chamada sincrona ao account-service (transferencia).",
            extra={"context": {"target_url": url, "error": str(exc)}},
        )
        raise AccountTransferServiceUnavailableError("account-service indisponivel") from exc

    if response.status_code == 422:
        raise SaldoInsuficienteUpstreamError()

    if response.status_code >= 400:
        logger.error(
            "Resposta inesperada do account-service (transferencia).",
            extra={"context": {"target_url": url, "status_code": response.status_code}},
        )
        raise AccountTransferServiceUnavailableError("account-service retornou erro inesperado")

    return response.json()
