# 05 — Criação de conta (versão síncrona provisória)

## Contexto / objetivo
Permitir a criação de uma conta a partir de um onboarding aprovado. Esta é uma versão **provisória e síncrona**: o account-service consulta diretamente o onboarding-service via REST antes de criar a conta. Essa versão será substituída pelo fluxo orientado a eventos na história [07-kafka-onboarding-eventos.md](07-kafka-onboarding-eventos.md) — implementar aqui apenas o suficiente para desbloquear o funil ponta a ponta antes do Kafka entrar em cena, sem investir em infraestrutura de retry/circuit breaker sofisticada que será descartada.

## Contrato afetado
`POST /v1/accounts` (account-service)

### Request body
```json
{
  "onboarding_id": "UUID",
  "tipo_conta": "corrente|poupanca"
}
```

### Comportamento
1. Account-service faz `GET /v1/onboarding/{onboarding_id}/internal` no onboarding-service (chamada síncrona REST, sem autenticação nesta fase — ver [security.md](../tech/security.md); é o endpoint interno definido em [03-onboarding-post.md](03-onboarding-post.md), não o `GET` público, porque só o interno retorna o `cpf` necessário para `accounts.cpf`).
2. Se o onboarding não existe: `404`.
3. Se o onboarding existe mas `status != "aprovado"`: `422`.
4. Se o onboarding está `aprovado` e não há conta ativa já criada para esse `onboarding_id`: cria a conta com `status: "ativa"`, `cpf` (decifrado do payload interno e regravado criptografado — ver [10-criptografia-cpf.md](10-criptografia-cpf.md)) e `tipo_conta` do request. `risco_score`/`risco_sinais` da conta herdam o valor de `risco_cadastro` do onboarding como ponto de partida (ver [02-modelo-dados.md](02-modelo-dados.md)).
5. Se já existe conta (não deletada) para esse `onboarding_id`: `409`.

### Respostas
- `201 Created`: `{ "id": "UUID", "status": "ativa", "created_at": "timestamp" }`
- `400 Bad Request`: `tipo_conta` ausente ou fora do enum (`corrente`, `poupanca`). `error_code: "VALIDATION_ERROR"`, `field: "tipo_conta"`.
- `404 Not Found`: `error_code: "ONBOARDING_NOT_FOUND"`.
- `409 Conflict`: `error_code: "ACCOUNT_ALREADY_EXISTS"`.
- `422 Unprocessable Entity`: `error_code: "ONBOARDING_NOT_APPROVED"`.

Formato de erro conforme [error-handling.md](../tech/error-handling.md).

## Critério de aceite
- [ ] Onboarding aprovado e sem conta prévia → `201` com conta criada em `accounts` (schema de [02-modelo-dados.md](02-modelo-dados.md)), `onboarding_id`, `cpf` e `tipo_conta` preenchidos.
- [ ] Conta criada herda `risco_score`/`risco_sinais` do `risco_cadastro` do onboarding aprovado.
- [ ] Request sem `tipo_conta` ou com valor fora do enum → `400` com `error_code: "VALIDATION_ERROR"`, `field: "tipo_conta"`.
- [ ] `onboarding_id` inexistente → `404` com `error_code: "ONBOARDING_NOT_FOUND"`.
- [ ] Onboarding com status `em_analise`, `reprovado_qualidade` ou `reprovado_fraude` → `422` com `error_code: "ONBOARDING_NOT_APPROVED"`.
- [ ] Segunda chamada para o mesmo `onboarding_id` já convertido em conta → `409` com `error_code: "ACCOUNT_ALREADY_EXISTS"`.
- [ ] Chamada ao onboarding-service indisponível (timeout/erro de rede) resulta em `500` no formato padrão, sem vazar detalhe de infraestrutura no `message`.
- [ ] Teste de contrato cobre os cenários acima (com onboarding-service mockado/stub, exceto o teste de interoperabilidade real já coberto na issue #10).

## Specs técnicas aplicáveis
- [api-conventions.md](../tech/api-conventions.md) — contrato REST, status codes.
- [error-handling.md](../tech/error-handling.md) — formato de erro.
- [security.md](../tech/security.md) — comunicação entre serviços sem autenticação nesta fase.
- [10-criptografia-cpf.md](10-criptografia-cpf.md) — `cpf` obtido via endpoint interno, decifrado e regravado criptografado em `accounts.cpf`.
