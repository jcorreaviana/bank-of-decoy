# 03 — Endpoint de criação de onboarding

## Contexto / objetivo
Primeiro endpoint de negócio do fluxo: recebe os dados do cliente que está tentando abrir conta e registra a solicitação de onboarding com status inicial `em_analise`. Não faz a análise de risco em si — isso é a história [04-onboarding-risco.md](04-onboarding-risco.md).

## Contrato afetado
`POST /v1/onboarding` (onboarding-service)

### Request body
```json
{
  "cpf": "string",
  "nome": "string",
  "data_nascimento": "date (YYYY-MM-DD)",
  "email": "string",
  "telefone": "string",
  "documento_tipo": "string",
  "documento_numero": "string",
  "dispositivo_id": "string",
  "ip_origem": "string"
}
```

### Respostas
- `201 Created`: onboarding criado.
  ```json
  {
    "id": "UUID",
    "status": "em_analise",
    "created_at": "timestamp"
  }
  ```
- `400 Bad Request`: payload inválido (campo obrigatório ausente, formato de CPF/email/data inválido). `error_code: "VALIDATION_ERROR"`, `field` preenchido com o campo inválido.
- `409 Conflict`: CPF já possui onboarding não deletado registrado. `error_code: "CPF_ALREADY_REGISTERED"`, `field: "cpf"`.

Formato de erro conforme [error-handling.md](../tech/error-handling.md).

### `GET /v1/onboarding/{id}` (onboarding-service)

Consulta o estado atual de um onboarding, incluindo o resultado da classificação de risco (ver [04-onboarding-risco.md](04-onboarding-risco.md)) quando já processada. Como a classificação roda logo após a criação e não no mesmo response do `POST` (ver 04), este é o endpoint que o cliente usa para obter o `status` final e o sinal de risco.

- `200 OK`:
  ```json
  {
    "id": "UUID",
    "status": "em_analise|aprovado|reprovado_qualidade|reprovado_fraude",
    "risco_cadastro": {
      "score": "number (0-100), null se ainda em_analise",
      "sinais": ["string", "..."]
    },
    "created_at": "timestamp"
  }
  ```
- `404 Not Found`: id inexistente ou com `deleted_at` preenchido. `error_code: "ONBOARDING_NOT_FOUND"`.

Formato de erro conforme [error-handling.md](../tech/error-handling.md).

## Critério de aceite
- [ ] Request válido retorna `201` com `id` (UUID) e `status: "em_analise"`.
- [ ] Registro é persistido em `onboardings` com todos os campos do payload (ver schema em [02-modelo-dados.md](02-modelo-dados.md)).
- [ ] Request sem campo obrigatório retorna `400` com `error_code: "VALIDATION_ERROR"` e `field` correto.
- [ ] Request com CPF de formato inválido (não numérico, tamanho incorreto) retorna `400` com `field: "cpf"`.
- [ ] Segunda tentativa de onboarding com o mesmo CPF (registro existente com `deleted_at IS NULL`) retorna `409` com `error_code: "CPF_ALREADY_REGISTERED"`.
- [ ] CPF, nome e demais dados pessoais nunca aparecem em log de nível `INFO` ou `DEBUG` (apenas o `id` do onboarding é logado nesses níveis).
- [ ] CPF e documento não trafegam em query string em nenhum momento do fluxo.
- [ ] `GET /v1/onboarding/{id}` retorna `200` com `risco_cadastro: { score, sinais }` preenchido após a classificação rodar.
- [ ] `GET /v1/onboarding/{id}` para id inexistente ou deletado retorna `404` com `error_code: "ONBOARDING_NOT_FOUND"`.
- [ ] Teste de contrato cobre: caminho feliz do `POST` e do `GET`, `400` (campo ausente e formato inválido), `409` e `404`.

## Specs técnicas aplicáveis
- [api-conventions.md](../tech/api-conventions.md) — prefixo `/v1/`, plural, status codes.
- [error-handling.md](../tech/error-handling.md) — formato de erro, `VALIDATION_ERROR`.
- [logging.md](../tech/logging.md) — regra de PII em log.
- [security.md](../tech/security.md) — CPF/documento nunca em query string.
