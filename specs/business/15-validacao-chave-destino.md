# 15 — Validação de chave de destino em transações

## Contexto

`transaction-service` nunca valida `pix_key_destino` — nem existência, nem status ativo. Qualquer valor é aceito como destino, mesmo que a chave não exista ou tenha sido cancelada (soft-deleted). Isso foi descoberto durante a análise da issue #15 (agente de oportunidade) e é um bug de correção real, não uma lacuna de cobertura teórica — pode ter afetado a integridade do dataset já gerado (issue #8).

## Objetivo

`POST /v1/transactions` deve validar `pix_key_destino` contra o `pix-key-service` antes de processar: a chave deve existir e estar ativa (não soft-deleted).

## Critério de aceite

- [ ] Chave de destino inexistente retorna 404
- [ ] Chave de destino soft-deleted (cancelada) retorna 422 (ex. `PIX_KEY_DESTINO_INATIVA`)
- [ ] Chave de destino válida e ativa segue o fluxo normal
- [ ] Testes cobrindo os 3 cenários
- [ ] Avaliação de impacto no dataset já gerado (issue #8): quantas transações no dataset atual têm destino inexistente ou inativo? Reportar o número antes de decidir sobre regeneração.

## Sinal de risco

Categoria da mudança: operacional (correção de validação ausente)
Serviço(s) afetado(s): transaction-service (crítico)

## Dependências

Nenhuma — correção direta sobre a issue #6 já fechada.
