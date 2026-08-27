"""Cliente REST sincrono para o pix-key-service (GET /v1/pix-keys/lookup),
usado para validar pix_key_destino antes de criar uma transacao
(specs/business/15-validacao-chave-destino.md).

Mesma filosofia sincrona/sem-retry de app/services/account_client.py.
"""

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_TIMEOUT_SECONDS = 5.0


class PixKeyDestinoNotFoundUpstreamError(Exception):
    """O pix-key-service respondeu 404 - pix_key_destino nunca existiu."""


class PixKeyServiceUnavailableError(Exception):
    """Falha na chamada sincrona ao pix-key-service (timeout, conexao
    recusada, resposta inesperada)."""


def fetch_pix_key_by_valor(valor: str, trace_id: str = "") -> dict:
    settings = get_settings()
    url = f"{settings.pix_key_service_url}/v1/pix-keys/lookup"
    headers = {"X-Trace-Id": trace_id} if trace_id else {}

    try:
        response = httpx.get(url, params={"valor": valor}, headers=headers, timeout=_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        logger.error(
            "Falha na chamada sincrona ao pix-key-service.",
            extra={"context": {"target_url": url, "error": str(exc)}},
        )
        raise PixKeyServiceUnavailableError("pix-key-service indisponivel") from exc

    if response.status_code == 404:
        raise PixKeyDestinoNotFoundUpstreamError()

    if response.status_code >= 400:
        logger.error(
            "Resposta inesperada do pix-key-service.",
            extra={"context": {"target_url": url, "status_code": response.status_code}},
        )
        raise PixKeyServiceUnavailableError("pix-key-service retornou erro inesperado")

    return response.json()
