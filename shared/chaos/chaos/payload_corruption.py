"""Corrupcao de payload de resposta para o tipo de falha
`payload_corrompido_sutil` (issue #52, specs/business/24-camada-caos-avancada.md).

Decisao de onde injetar (confirmada com o usuario durante a
implementacao): na RESPOSTA de cada endpoint, dentro do proprio
ChaosMiddleware, depois do router real rodar via `call_next` - nao no
request recebido. Motivo: nenhum schema de REQUEST dos 4 servicos tem
campo opcional hoje (todos os campos de escrita sao obrigatorios), e o
unico jeito de corromper um "campo numerico como string" no request
exigiria reescrever o body ASGI antes da validacao Pydantic rodar (bem
mais invasivo). Os schemas de RESPOSTA, por outro lado, ja tem campos
opcionais de verdade (ex. RiscoCadastro.score) e sao mais simples de
interceptar aqui, ja que o middleware ja tem a resposta em maos apos
`call_next`. "Downstream" e quem consome essa resposta - normalmente
outro microservico, as vezes o proprio cliente HTTP externo.

Cada receita abaixo tem um consumidor real, verificado no codigo (nao
e so um exemplo hipotetico):

- account-service GET /v1/accounts/{account_id}: `saldo` (float) vira
  string - passa como JSON valido, mas o tipo mudou. Hoje nenhum
  consumidor sincrono le esse campo (transaction-service, unico client,
  so le `status` em app/services/account_client.py), entao o efeito e
  silencioso por definicao - exatamente o "campo numerico como string
  coercivel" da spec.
- onboarding-service GET /v1/onboarding/{id}/internal: remove
  `risco_cadastro.score` (campo ja opcional no schema,
  `RiscoCadastro.score: float | None`). account-service faz
  `risco_cadastro.get("score")` ao criar a conta
  (app/services/account_service.py:92) - o valor vira `None` sem
  nenhum erro, e a conta fica com `risco_score` incorreto em silencio
  (afeta o dataset de fraude, nao quebra o fluxo sincrono).
- pix-key-service GET /v1/pix-keys/lookup: forca `ativa=true` sempre -
  transaction-service usa exatamente esse campo para rejeitar uma
  transacao para chave cancelada
  (app/services/transaction_service.py:59, `if not
  pix_key_destino["ativa"]: raise PixKeyDestinoInativaError()`).
  Forcar sempre "ativa" faz uma transacao para chave cancelada ser
  aceita silenciosamente em vez de rejeitada - o cenario mais "perigoso"
  das 4 receitas, de proposito (e o que se espera de caos realista).
- transaction-service POST /v1/transactions: `risco_transacao.score`
  (float, obrigatorio) vira string - mesmo padrao do account-service
  acima, na resposta do endpoint de escrita principal do servico.
"""

import json
import logging

from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("chaos")


def _get_container(data: dict, path: list[str]):
    """Anda ate o dict que contem o campo-folha (path[-1]), sem descer
    nele. Retorna None se o caminho nao existir - corrupcao vira no-op
    em vez de erro, caso o shape da resposta mude no futuro."""
    node = data
    for key in path[:-1]:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node if isinstance(node, dict) else None


def _stringify_leaf(data: dict, path: list[str]) -> dict:
    container = _get_container(data, path)
    leaf = path[-1]
    if container is not None and container.get(leaf) is not None:
        container[leaf] = str(container[leaf])
    return data


def _drop_leaf(data: dict, path: list[str]) -> dict:
    container = _get_container(data, path)
    if container is not None:
        container.pop(path[-1], None)
    return data


def _force_leaf(data: dict, path: list[str], value) -> dict:
    container = _get_container(data, path)
    if container is not None:
        container[path[-1]] = value
    return data


_RECIPES = {
    ("GET", "/v1/accounts/{account_id}"): lambda body: _stringify_leaf(body, ["saldo"]),
    ("GET", "/v1/onboarding/{onboarding_id}/internal"): lambda body: _drop_leaf(body, ["risco_cadastro", "score"]),
    ("GET", "/v1/pix-keys/lookup"): lambda body: _force_leaf(body, ["ativa"], True),
    ("POST", "/v1/transactions"): lambda body: _stringify_leaf(body, ["risco_transacao", "score"]),
}


async def maybe_corrupt_response(request: Request, response: Response) -> Response:
    """Chamada pelo ChaosMiddleware quando o sorteio escolhe
    payload_corrompido_sutil, depois de `call_next` (a rota real ja
    rodou e ja populou request.scope["route"]). Sem receita para a rota
    atual, ou resposta nao-2xx/nao-JSON: devolve a resposta original
    sem tocar nela."""
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    recipe = _RECIPES.get((request.method, route_path))
    if recipe is None or response.status_code >= 300:
        return response

    content_type = response.headers.get("content-type", "")
    if "application/json" not in content_type:
        return response

    body_chunks = [chunk async for chunk in response.body_iterator]
    raw_body = b"".join(body_chunks)
    try:
        data = json.loads(raw_body)
    except ValueError:
        # Nao deveria acontecer com content-type application/json, mas por
        # seguranca devolve o corpo original intacto em vez de quebrar.
        return Response(
            content=raw_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )

    corrupted = recipe(data)
    corrupted_body = json.dumps(corrupted).encode("utf-8")

    headers = dict(response.headers)
    headers["content-length"] = str(len(corrupted_body))

    logger.warning(
        "Payload de resposta corrompido pela camada de caos.",
        extra={
            "context": {
                "chaos_injected": True,
                "failure_type": "payload_corrompido_sutil",
                "route": route_path,
                "method": request.method,
            }
        },
    )

    return Response(
        content=corrupted_body,
        status_code=response.status_code,
        headers=headers,
        media_type="application/json",
    )
