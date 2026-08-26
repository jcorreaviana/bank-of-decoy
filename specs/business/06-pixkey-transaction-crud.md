# 06 — CRUD de chave PIX e criação de transação

## Contexto / objetivo
Habilitar as duas operações de domínio que faltam para o funil ponta a ponta funcionar: registrar/remover chave PIX vinculada a uma conta, e criar uma transação PIX com um gerador de risco simples classificando parte das transações como suspeitas.

## Contrato afetado

### `POST /v1/pix-keys` (pix-key-service)
Request:
```json
{ "account_id": "UUID", "tipo": "cpf|email|telefone|aleatoria", "valor": "string" }
```
- `201`: `{ "id": "UUID", "tipo": "string", "valor": "string", "created_at": "timestamp" }`
- `400`: `error_code: "VALIDATION_ERROR"` — `tipo` fora do enum ou `valor` em formato incompatível com `tipo` (ex. `tipo: "email"` com `valor` que não é email).
- `409`: `error_code: "PIX_KEY_ALREADY_REGISTERED"` — `valor` já registrado (não deletado) para qualquer conta.

### `DELETE /v1/pix-keys/{id}` (pix-key-service)
- `204`: chave marcada como removida (soft delete — ver [database.md](../tech/database.md)).
- `404`: `error_code: "PIX_KEY_NOT_FOUND"` — id inexistente ou já deletado.

### `POST /v1/transactions` (transaction-service)
Request:
```json
{ "account_id": "UUID", "pix_key_destino": "string", "valor": "number" }
```
- `201`:
  ```json
  {
    "id": "UUID",
    "status": "concluida|suspeita",
    "risco_transacao": {
      "score": "number (0-100)",
      "sinais": ["string", "..."]
    },
    "created_at": "timestamp"
  }
  ```
- `400`: `error_code: "VALIDATION_ERROR"` — `valor` <= 0 ou `pix_key_destino` vazio.
- `422`: `error_code: "ACCOUNT_NOT_ACTIVE"` — `account_id` não corresponde a conta com `status: "ativa"`.

Formato de erro conforme [error-handling.md](../tech/error-handling.md) em todos os casos.

## Gerador de risco da transação
- Cada transação criada é classificada em `concluida` ou `suspeita` por regras simples e determinísticas (mesma filosofia de [04-onboarding-risco.md](04-onboarding-risco.md): explicáveis, não ML).
- Assim como no onboarding, cada regra avaliada contribui um sinal individual para `risco_sinais` (ex. `valor_atipico`, `horario_atipico`, `destinatario_novo`, `velocidade_alta`) e a combinação de sinais disparados determina `risco_score` (0-100) — uma transação pode acionar mais de um sinal simultaneamente. `status: "suspeita"` é atribuído quando ao menos um sinal de suspeita dispara; caso contrário, `"concluida"`. Ambos os campos são persistidos em `transactions` (ver [02-modelo-dados.md](02-modelo-dados.md)).
- Percentual alvo de transações `suspeita`: **1% a 2%** do total processado.
- Transação `suspeita` ainda retorna `201` (a suspeita é um sinal registrado, não um bloqueio nesta fase) — bloqueio automático de transação suspeita fica fora do escopo da Fase 1.

## Critério de aceite
- [ ] `POST /v1/pix-keys` com payload válido cria a chave e retorna `201`.
- [ ] `POST /v1/pix-keys` com `valor` já registrado (chave não deletada) retorna `409`.
- [ ] `DELETE /v1/pix-keys/{id}` faz soft delete (`deleted_at` preenchido, registro não removido fisicamente) e retorna `204`.
- [ ] `DELETE /v1/pix-keys/{id}` para id já deletado ou inexistente retorna `404`.
- [ ] `POST /v1/transactions` com conta ativa e payload válido cria a transação com `status` `concluida` ou `suspeita`, e `risco_transacao.score`/`risco_transacao.sinais` preenchidos.
- [ ] `POST /v1/transactions` para conta não `ativa` (bloqueada, encerrada ou inexistente) retorna `422` com `error_code: "ACCOUNT_NOT_ACTIVE"`.
- [ ] Rodando o gerador de risco sobre uma amostra grande (ex. 10.000 transações sintéticas), o percentual de `suspeita` fica entre 1% e 2%.
- [ ] Testes de contrato cobrem caminho feliz e cada erro documentado acima, para os dois serviços.

## Specs técnicas aplicáveis
- [error-handling.md](../tech/error-handling.md) — formato de erro.
- [database.md](../tech/database.md) — soft delete em `pix_keys`, schema de `transactions`.
- [api-conventions.md](../tech/api-conventions.md) — contrato REST.
