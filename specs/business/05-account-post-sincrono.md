# 05 — Criação de conta (versão síncrona provisória)

## Contexto / objetivo
Permitir a criação de uma conta a partir de um onboarding aprovado. Esta é uma versão **provisória e síncrona**: o account-service consulta diretamente o onboarding-service via REST antes de criar a conta. Essa versão será substituída pelo fluxo orientado a eventos na história [07-kafka-onboarding-eventos.md](07-kafka-onboarding-eventos.md) — implementar aqui apenas o suficiente para desbloquear o funil ponta a ponta antes do Kafka entrar em cena, sem investir em infraestrutura de retry/circuit breaker sofisticada que será descartada.

## Contrato afetado
`POST /v1/accounts` (account-service)

### Request body
```json
{
  "onboarding_id": "UUID"
}
```

### Comportamento
1. Account-service faz `GET /v1/onboarding/{onboarding_id}` no onboarding-service (chamada síncrona REST, sem autenticação nesta fase — ver [security.md](../tech/security.md)).
2. Se o onboarding não existe: `404`.
3. Se o onboarding existe mas `status != "aprovado"`: `422`.
4. Se o onboarding está `aprovado` e não há conta ativa já criada para esse `onboarding_id`: cria a conta com `status: "ativa"`.
5. Se já existe conta (não deletada) para esse `onboarding_id`: `409`.

### Respostas
- `201 Created`: `{ "id": "UUID", "status": "ativa", "created_at": "timestamp" }`
- `404 Not Found`: `error_code: "ONBOARDING_NOT_FOUND"`.
- `409 Conflict`: `error_code: "ACCOUNT_ALREADY_EXISTS"`.
- `422 Unprocessable Entity`: `error_code: "ONBOARDING_NOT_APPROVED"`.

Formato de erro conforme [error-handling.md](../tech/error-handling.md).

## Critério de aceite
- [ ] Onboarding aprovado e sem conta prévia → `201` com conta criada em `accounts` (schema de [02-modelo-dados.md](02-modelo-dados.md)), `onboarding_id` preenchido.
- [ ] `onboarding_id` inexistente → `404` com `error_code: "ONBOARDING_NOT_FOUND"`.
- [ ] Onboarding com status `em_analise`, `reprovado_qualidade` ou `reprovado_fraude` → `422` com `error_code: "ONBOARDING_NOT_APPROVED"`.
- [ ] Segunda chamada para o mesmo `onboarding_id` já convertido em conta → `409` com `error_code: "ACCOUNT_ALREADY_EXISTS"`.
- [ ] Chamada ao onboarding-service indisponível (timeout/erro de rede) resulta em `500` no formato padrão, sem vazar detalhe de infraestrutura no `message`.
- [ ] Teste de contrato cobre os quatro cenários acima (com onboarding-service mockado/stub).

## Specs técnicas aplicáveis
- [api-conventions.md](../tech/api-conventions.md) — contrato REST, status codes.
- [error-handling.md](../tech/error-handling.md) — formato de erro.
- [security.md](../tech/security.md) — comunicação entre serviços sem autenticação nesta fase.
