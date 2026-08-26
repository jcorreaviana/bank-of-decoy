# Specs técnicas transversais

Decisões técnicas que orientam a implementação de todos os microserviços do bank-of-decoy. Válidas para todo serviço, independente da história de negócio que ele implementa.

1. [stack.md](stack.md) — linguagem, frameworks, estrutura de pastas por serviço.
2. [logging.md](logging.md) — formato de log estruturado, níveis, regras de PII.
3. [database.md](database.md) — convenções de schema Postgres, soft delete, nomenclatura.
4. [error-handling.md](error-handling.md) — formato padrão de resposta de erro, middleware global.
5. [api-conventions.md](api-conventions.md) — versionamento de rota, nomenclatura de recurso, paginação.
6. [testing.md](testing.md) — cobertura mínima, testes de contrato.
7. [observability.md](observability.md) — métricas Prometheus, golden signals.
8. [messaging.md](messaging.md) — convenção de tópico Kafka, envelope de evento, idempotência.
9. [security.md](security.md) — autenticação entre serviços, tratamento de PII, segredos.
10. [infrastructure.md](infrastructure.md) — docker-compose local, portas dos serviços, variáveis de ambiente.
