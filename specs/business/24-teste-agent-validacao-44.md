# 24 — Teste agent validacao 44

## Contexto

O comportamento observado não respeita a convenção de paginacao documentada para listagens da API, retornando todos os 4200 registros em uma unica resposta sem limites de paginacao.

Comportamento observado: GET /v1/accounts/{id}/transacoes retornou os 4200 registros da conta em uma unica resposta JSON, sem parametros de paginacao (limit/offset) nem cabecalhos de contagem, e sem erro apesar do volume alto.

## Objetivo

api-conventions.md

## Critério de aceite

- [ ] - O comportamento observado não respeita a convenção de paginacao documentada para listagens da API.
- [ ] - A API não deve retornar todos os registros em uma unica resposta sem limites de paginacao.
- [ ] - O comportamento observado não gerou erros ou excecoes.
- [ ] - A API deve retornar uma resposta com cabecalhos de contagem para indicar a quantidade de registros retornados.

## Sinal de risco

Categoria da mudança: regra de negócio
Serviço(s) afetado(s): a definir na triagem

## Dependências

Nenhuma.
