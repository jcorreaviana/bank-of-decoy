# Cenário: onboarding_get_inexistente

## Veredito
GAP

## Racional
O trecho de spec não menciona explicitamente o comportamento esperado para o caso de um onboarding inexistente, e o comportamento observado (500, error_code=INTERNAL_ERROR) não é mencionado como um erro esperado em nenhum dos casos de erro listados no spec.

## Comportamento observado
GET /v1/onboarding/{id inexistente} retornou 500, error_code=INTERNAL_ERROR

## Passos de reprodução
1. GET /v1/onboarding/{id inexistente} retornou 500, error_code=INTERNAL_ERROR
