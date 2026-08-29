# 25 — Teste agent validacao 44b

## Contexto

Lacuna encontrada na validação de limite de chaves por conta no serviço PIX-Key, permitindo a criação de quarta chave aleatória sem restrição.

Comportamento observado: POST /v1/pix-keys com account_id que ja possui 3 chaves ativas retornou 201 e criou uma quarta chave aleatoria, sem nenhuma validacao de limite.

## Objetivo

spec de pix-key-service

## Critério de aceite

- [ ] A criação de quarta chave aleatória sem restrição de limite de chaves por conta deve ser validada e rejeitada.
- [ ] O serviço PIX-Key deve retornar um erro de validação para a criação de quarta chave aleatória sem restrição de limite de chaves por conta.
- [ ] A documentação da spec de pix-key-service deve ser revisada para incluir a validação do limite de chaves por conta.
- [ ] A implementação de uma validação de limite de chaves por conta deve ser feita no serviço PIX-Key.

## Sinal de risco

Categoria da mudança: regra de negócio
Serviço(s) afetado(s): a definir na triagem

## Dependências

Nenhuma.
