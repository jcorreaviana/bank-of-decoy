# API Conventions

## Versionamento e prefixo
- Toda rota é prefixada com `/v1/` (ex. `/v1/accounts`).
- Mudança incompatível de contrato exige nova versão de prefixo (`/v2/`), nunca alteração retroativa de `/v1/`.

## Nomenclatura de recursos
- Recursos sempre no plural: `/v1/accounts`, `/v1/pix-keys`, `/v1/transactions` — nunca singular.
- Palavras compostas em `kebab-case` na URL (ex. `/v1/pix-keys`, não `/v1/pixkeys` ou `/v1/pix_keys`).
- Sub-recursos aninhados sob o pai quando a relação é de posse (ex. `/v1/accounts/{account_id}/transactions`).

## Métodos HTTP
- `GET` para leitura (idempotente, sem side effect).
- `POST` para criação de recurso ou ação que não é idempotente por natureza (ex. `/v1/transactions`).
- `PATCH` para atualização parcial.
- `DELETE` mapeia para soft delete no backend (ver [database.md](database.md)) — nunca remoção física.

## Paginação
- Toda listagem usa paginação por cursor: `?cursor=<opaque>&limit=<n>`.
- `limit` default: 20. `limit` máximo: 100 — valores acima retornam `VALIDATION_ERROR` (ver [error-handling.md](error-handling.md)).
- Resposta de listagem tem o formato:
```json
{
  "items": [...],
  "next_cursor": "string|null"
}
```
- `next_cursor: null` indica fim da listagem.

## Status codes
- `200`: leitura ou atualização com sucesso.
- `201`: criação com sucesso.
- `204`: sucesso sem corpo de resposta (ex. remoção).
- `400`: erro de validação de request.
- `404`: recurso não encontrado.
- `409`: conflito de estado (ex. chave PIX já registrada).
- `422`: regra de negócio violada (request bem formado, mas semanticamente inválido).
- `500`: erro não mapeado (ver [error-handling.md](error-handling.md)).
