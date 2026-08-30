# 25 — Onboarding get inexistente

## Contexto

O comportamento observado para o cenário 'onboarding_get_inexistente' coincide com o comportamento esperado especificado na spec, retornando 404 com error_code "ONBOARDING_NOT_FOUND" para um onboarding inexistente.

Comportamento observado: GET /v1/onboarding/{id inexistente} retornou 404, error_code=ONBOARDING_NOT_FOUND

## Objetivo

api-conventions.md, especificamente o endpoint GET /v1/onboarding/{id} e o error_code "ONBOARDING_NOT_FOUND".

## Critério de aceite

- [ ] O retorno de 404 com error_code "ONBOARDING_NOT_FOUND" é consistente com o comportamento esperado especificado na spec.
- [ ] O endpoint GET /v1/onboarding/{id} é tratado corretamente e retorna o erro correto para um onboarding inexistente.
- [ ] Testes de cobertura de cenários de erro estão documentados na spec para garantir a cobertura completa do comportamento esperado.

## Sinal de risco

Categoria da mudança: regra de negócio
Serviço(s) afetado(s): a definir na triagem

## Dependências

Nenhuma.
