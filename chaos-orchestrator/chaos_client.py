"""Cliente HTTP do chaos-orchestrator (issue #53) contra
`POST /internal/chaos/config` de cada servico (issue #51,
shared/chaos/chaos/router.py) - mesmo header X-Internal-Token
(shared/chaos/chaos/internal_auth.py) usado pelos 4 microservicos.

Falha de rede/timeout ao chamar um servico e responsabilidade de quem chama
(orchestrator.py) tratar sem derrubar o resto da timeline - esta funcao so
propaga a excecao (httpx.HTTPError), nunca a engole.
"""

from __future__ import annotations

import httpx

TOKEN_HEADER = "X-Internal-Token"
TOKEN_ENV_VAR = "CHAOS_INTERNAL_TOKEN"  # mesma variavel usada pelos 4 servicos

DEFAULT_TIMEOUT_SECONDS = 10.0


def post_chaos_config(
    base_url: str,
    payload: dict,
    *,
    token: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """POSTa `payload` em `{base_url}/internal/chaos/config`. Deixa
    `httpx.HTTPError` (timeout, conexao recusada, status >= 400) propagar -
    quem chama decide como logar/seguir em frente."""
    response = httpx.post(
        f"{base_url}/internal/chaos/config",
        json=payload,
        headers={TOKEN_HEADER: token},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()
