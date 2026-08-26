"""Cliente REST sincrono para o endpoint interno do onboarding-service
(specs/business/10-criptografia-cpf.md).

So o suficiente para provar a interoperabilidade da criptografia entre os
dois servicos: busca o onboarding via GET /v1/onboarding/{id}/internal e
decifra o `cpf` recebido (ainda criptografado nesse payload - ver
onboarding-service/app/routers/onboarding.py). A orquestracao completa de
criacao de conta (404/422/409/503, retry, etc) e escopo da issue #5,
ainda nao retomada - nao implementar aqui.
"""

import httpx

from app.core.config import get_settings
from app.core.crypto import decrypt_value

_TIMEOUT_SECONDS = 5.0


def fetch_onboarding_internal(onboarding_id: str, trace_id: str = "") -> dict:
    """Retorna o payload do endpoint interno com `cpf` ja decifrado (texto
    puro) - nunca logar esse retorno."""
    settings = get_settings()
    url = f"{settings.onboarding_service_url}/v1/onboarding/{onboarding_id}/internal"
    headers = {"X-Trace-Id": trace_id} if trace_id else {}

    response = httpx.get(url, headers=headers, timeout=_TIMEOUT_SECONDS)
    response.raise_for_status()

    payload = response.json()
    payload["cpf"] = decrypt_value(payload["cpf"])
    return payload
