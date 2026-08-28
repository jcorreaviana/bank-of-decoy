"""Cliente REST sincrono para o endpoint interno do onboarding-service
(specs/business/10-criptografia-cpf.md, specs/business/05-account-post-sincrono.md).

Versao provisoria e sincrona (issue #5) - sera substituida pelo fluxo de
eventos Kafka na issue #7. Deliberadamente sem retry/circuit breaker
sofisticado: uma falha aqui e justamente o tipo de acoplamento que a
camada de caos (Fase 2) vai explorar depois, entao ela deve ficar visivel
(log + erro claro), nao escondida atras de tentativas automaticas.
"""

import httpx

from app.core.config import get_settings
from app.core.crypto import decrypt_value
from app.core.logging import get_logger

logger = get_logger(__name__)

_TIMEOUT_SECONDS = 5.0

# Client persistente (nao httpx.get avulso) para reaproveitar conexao/pool
# TCP entre chamadas - correcao preventiva do mesmo padrao que causou o
# sinal latencia_alta nas issues #34/#37/#38 (httpx.get() avulso abre um
# Client novo a cada chamada).
_client = httpx.Client(timeout=_TIMEOUT_SECONDS)


class OnboardingNotFoundUpstreamError(Exception):
    """O onboarding-service respondeu 404 - onboarding_id inexistente ou deletado."""


class OnboardingServiceUnavailableError(Exception):
    """Falha na chamada sincrona ao onboarding-service (timeout, conexao
    recusada, resposta inesperada). Propaga para o handler generico de 500
    (specs/business/05-account-post-sincrono.md: "resulta em 500 no
    formato padrao, sem vazar detalhe de infraestrutura") - o detalhe fica
    apenas no log, nunca na resposta ao cliente."""


def fetch_onboarding_internal(onboarding_id: str, trace_id: str = "") -> dict:
    """Busca o onboarding via o endpoint interno e retorna o payload com
    `cpf` ja decifrado (texto puro) - nunca logar esse retorno."""
    settings = get_settings()
    url = f"{settings.onboarding_service_url}/v1/onboarding/{onboarding_id}/internal"
    headers = {"X-Trace-Id": trace_id} if trace_id else {}

    try:
        response = _client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        logger.error(
            "Falha na chamada sincrona ao onboarding-service.",
            extra={"context": {"target_url": url, "onboarding_id": onboarding_id, "error": str(exc)}},
        )
        raise OnboardingServiceUnavailableError("onboarding-service indisponivel") from exc

    if response.status_code == 404:
        raise OnboardingNotFoundUpstreamError()

    if response.status_code >= 400:
        logger.error(
            "Resposta inesperada do onboarding-service.",
            extra={
                "context": {
                    "target_url": url,
                    "onboarding_id": onboarding_id,
                    "status_code": response.status_code,
                }
            },
        )
        raise OnboardingServiceUnavailableError("onboarding-service retornou erro inesperado")

    payload = response.json()
    payload["cpf"] = decrypt_value(payload["cpf"])
    return payload
