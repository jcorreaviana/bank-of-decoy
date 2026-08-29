"""Controle de acesso do endpoint interno de config de caos
(specs/business/24-camada-caos-avancada.md; exigencia de isolamento em
specs/tech/security.md: "o endpoint interno precisa estar de fato
inacessivel externamente").

Nao ha segmentacao de rede Docker hoje - todos os servicos publicam a
porta direto pro host em docker-compose.yml/docker-compose.test.yml
(`ports:`, nao `expose:`), entao "so acessivel na rede interna" nao e
hoje garantido por topologia. A unica forma enforcavel em codigo,
independente de topologia de rede, e um segredo compartilhado por
variavel de ambiente - mesmo padrao de "credencial via env var, nunca
hardcoded" ja usado por CPF_ENCRYPTION_KEY (specs/tech/security.md).

Fail closed: se CHAOS_INTERNAL_TOKEN nao estiver definido, todo acesso
e negado - nao existe um modo aberto por omissao de configuracao.
"""

import hmac
import os

from starlette.requests import Request

TOKEN_HEADER = "x-internal-token"
TOKEN_ENV_VAR = "CHAOS_INTERNAL_TOKEN"


def is_internal_request_authorized(request: Request) -> bool:
    expected = os.environ.get(TOKEN_ENV_VAR, "")
    if not expected:
        return False

    provided = request.headers.get(TOKEN_HEADER)
    if not provided:
        return False

    return hmac.compare_digest(provided, expected)
