# 26 — Onboarding get inexistente

## Contexto

O comportamento observado para o cenário 'onboarding_get_inexistente' coincide com o comportamento esperado especificado na spec, retornando 404 com error_code "ONBOARDING_NOT_FOUND" para um onboarding inexistente.

Comportamento observado: GET /v1/onboarding/{id inexistente} retornou 404, error_code=ONBOARDING_NOT_FOUND

## Objetivo

api-conventions.md, especificamente a seção "Códigos de erro" que define o comportamento para o error_code "ONBOARDING_NOT_FOUND".

## Critério de aceite

- [ ] O retorno de 404 com error_code "ONBOARDING_NOT_FOUND" é consistente com a spec.
- [ ] O comportamento é coerente com o cenário 'onboarding_get_inexistente'.
- [ ] A documentação de erros está clara e precisa.

## Sinal de risco

Categoria da mudança: regra de negócio
Serviço(s) afetado(s): a definir na triagem

## Dependências

Nenhuma.
