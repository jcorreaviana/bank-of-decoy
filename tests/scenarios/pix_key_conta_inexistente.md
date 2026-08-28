# Cenário: pix_key_conta_inexistente

## Veredito
GAP

## Racional
O trecho de spec especifica que `POST /v1/pix-keys` com conta inexistente retorna `404`, mas o comportamento observado retornou `201` com a criação da chave.

## Comportamento observado
POST /v1/pix-keys com account_id (e0ac03a9-59be-4a4f-9a93-5570edc809ce) que nunca existiu em account-service retornou 201 (chave criada)

## Passos de reprodução
1. POST /v1/pix-keys com account_id (e0ac03a9-59be-4a4f-9a93-5570edc809ce) que nunca existiu em account-service retornou 201 (chave criada)
