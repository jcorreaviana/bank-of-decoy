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

## Critério de aceite
- [ ] Request válido retorna `201` com `id` (UUID) e `status: "em_analise"`.
- [ ] Registro é persistido em `onboardings` com todos os campos do payload (ver schema em [02-modelo-dados.md](02-modelo-dados.md)).
- [ ] Request sem campo obrigatório retorna `400` com `error_code: "VALIDATION_ERROR"` e `field` correto.
- [ ] Request com CPF de formato inválido (não numérico, tamanho incorreto) retorna `400` com `field: "cpf"`.
- [ ] Segunda tentativa de onboarding com o mesmo CPF (registro existente com `deleted_at IS NULL`) retorna `409` com `error_code: "CPF_ALREADY_REGISTERED"`.
- [ ] CPF, nome e demais dados pessoais nunca aparecem em log de nível `INFO` ou `DEBUG` (apenas o `id` do onboarding é logado nesses níveis).
- [ ] CPF e documento não trafegam em query string em nenhum momento do fluxo.
- [ ] Teste de contrato cobre: caminho feliz, `400` (campo ausente e formato inválido) e `409`.

## Specs técnicas aplicáveis
- [api-conventions.md](../tech/api-conventions.md) — prefixo `/v1/`, plural, status codes.
- [error-handling.md](../tech/error-handling.md) — formato de erro, `VALIDATION_ERROR`.
- [logging.md](../tech/logging.md) — regra de PII em log.
- [security.md](../tech/security.md) — CPF/documento nunca em query string.
