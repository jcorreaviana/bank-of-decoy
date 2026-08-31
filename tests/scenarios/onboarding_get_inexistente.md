# Cenário: onboarding_get_inexistente

## Veredito
GAP

## Racional
O trecho de spec especifica claramente o comportamento esperado para o caso de um onboarding inexistente, que é retornar 404 com error_code "ONBOARDING_NOT_FOUND". O comportamento observado ao executar o cenario 'onboarding_get_inexistente' também retorna 404 com error_code "ONBOARDING_NOT_FOUND", o que coincide com o comportamento esperado.

## Comportamento observado
GET /v1/onboarding/{id inexistente} retornou 404, error_code=ONBOARDING_NOT_FOUND

## Passos de reprodução
1. GET /v1/onboarding/{id inexistente} retornou 404, error_code=ONBOARDING_NOT_FOUND
