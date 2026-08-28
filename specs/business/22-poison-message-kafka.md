# 22 — Tratamento de poison message no consumer Kafka

## Contexto

Diagnosticado durante investigação de um achado paralelo (log_critico_repetido no account-service): o consumer de `onboarding.aprovado` não tem tratamento de poison message — uma mensagem que falha permanentemente (não transitório) nunca avança o offset, causando reprocessamento infinito a cada restart. Causa raiz observada: mensagens cifradas com uma chave de criptografia já rotacionada/invalidada (issue #26) ficaram irrecuperáveis, mas o consumer trata isso como falha transitória.

## Objetivo

Implementar tratamento real de poison message: contador de tentativas por evento, e após N falhas, mover para dead-letter (tópico Kafka dedicado ou tabela) em vez de tentar reprocessar para sempre.

## Critério de aceite

- [ ] Contador de tentativas por evento implementado
- [ ] Após N falhas (definir N), evento vai para dead-letter, offset avança normalmente
- [ ] Dead-letter consultável (tópico ou tabela) para investigação posterior
- [ ] Teste simulando uma mensagem permanentemente inválida, confirmando que não trava o consumer indefinidamente

## Lição de processo (registrar também)

Documentar no runbook de rotação de chave de criptografia: antes de rotacionar, drenar/consumir mensagens pendentes cifradas com a chave antiga, ou tratar explicitamente esse cenário — a issue #26 rotacionou sem esse passo, causando este incidente.

## Sinal de risco

Categoria da mudança: operacional (robustez de infraestrutura de mensageria)
Serviço(s) afetado(s): account-service (alto)

## Dependências

Nenhuma bloqueante. Relacionada à issue #26 (já fechada) e à decisão original da #7 (escopo sem dead-letter, documentada como simplificação deliberada).
