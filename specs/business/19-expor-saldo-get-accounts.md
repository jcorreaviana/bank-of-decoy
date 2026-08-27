# 19 — Expor saldo em GET /v1/accounts/{id}

## Contexto

A issue #18 implementou o mecanismo de saldo (transferência atômica, débito/crédito), mas o endpoint `GET /v1/accounts/{id}` nunca foi atualizado para incluir o campo `saldo` na resposta. Achado durante a verificação de fechamento das issues #17/#18.

## Objetivo

`GET /v1/accounts/{id}` deve retornar o `saldo` atual da conta, além dos campos já existentes (status, risco).

## Critério de aceite

- [ ] Resposta do `GET /v1/accounts/{id}` inclui `saldo`
- [ ] Teste de contrato cobrindo o novo campo na resposta
- [ ] Nenhuma mudança em outros campos da resposta já existentes

## Sinal de risco

Categoria da mudança: operacional (exposição de campo já existente no banco, sem nova lógica de negócio)
Serviço(s) afetado(s): account-service (alto)

## Dependências

Depende da issue #18 (já fechada).
