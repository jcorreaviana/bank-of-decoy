# Cenário: pix_key_conta_inexistente

## Veredito
GAP

## Racional
O trecho de spec especifica que `POST /v1/pix-keys` com conta inexistente retorna `404`, mas o comportamento observado retornou `201` com a chave criada.

## Comportamento observado
POST /v1/pix-keys com account_id (76cafda2-c43b-4f38-a103-0b4e213c6412) que nunca existiu em account-service retornou 201 (chave criada)

## Passos de reprodução
1. POST /v1/pix-keys com account_id (76cafda2-c43b-4f38-a103-0b4e213c6412) que nunca existiu em account-service retornou 201 (chave criada)
