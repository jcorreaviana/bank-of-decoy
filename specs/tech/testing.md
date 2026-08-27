# Testing

## Isolamento do banco em testes (regra crítica)

**Suites de teste NUNCA apontam `DATABASE_URL` para o banco persistente do ambiente principal.** Sempre um banco de teste dedicado ou o ambiente efêmero (`docker-compose.test.yml`).

- Motivo: um incidente real (issue #15/#16) apagou as 500.980 contas do dataset de volumetria (issue #8) porque a suíte de contrato do `account-service` rodou contra o banco persistente — a fixture autouse de limpeza (`TRUNCATE accounts`) não tinha nenhuma proteção. `pix-key-service` e `transaction-service` escaparam do mesmo risco por sorte (tabelas vazias no momento), não por proteção real.
- Como o ambiente efêmero de teste reaproveita as mesmas portas e os mesmos nomes de banco do ambiente principal por design (`docker-compose.test.yml` substitui o principal, não roda em paralelo — ver `README.md`), a `DATABASE_URL` sozinha **não é suficiente** para diferenciar os dois ambientes.
- Toda fixture que faz `TRUNCATE`/`DELETE` em massa chama `require_disposable_database(settings.database_url)` do pacote compartilhado `shared/test_safety` **antes** de qualquer operação destrutiva. Essa função aborta a suíte (não apenas pula o teste) a menos que a variável de ambiente `TESTING=true` esteja setada explicitamente — só definir `TESTING=true` depois de confirmar manualmente que o banco apontado é descartável.
- Essa trava é código, não só convenção documentada aqui — está implementada nos 4 serviços (`onboarding-service`, `account-service`, `pix-key-service`, `transaction-service`).

## Cobertura mínima
- 80% de cobertura em código de lógica de domínio: regras de risco, validações de negócio, cálculos, máquinas de estado (ex. `app/services/`).
- Sem exigência de cobertura em código de infraestrutura: configuração de conexão de banco, setup de logging, bootstrap da app (`app/core/`), migrations.
- Cobertura medida por `pytest-cov`, configurada para reportar apenas os módulos sujeitos à exigência (`app/services/`, `app/models/` com lógica).

## Testes de contrato
- Cada endpoint REST tem teste de contrato cobrindo:
  - Caminho feliz (request válido → status e shape de resposta esperados).
  - Cada erro documentado na spec de negócio do serviço (status, `error_code` e `field` corretos — ver [error-handling.md](error-handling.md)).
- Testes de contrato usam `httpx.AsyncClient` contra a app FastAPI (sem subir servidor real), com banco de teste isolado (schema ou container dedicado).
- Testes de contrato vivem em `tests/contract/`, um arquivo por recurso.

## Testes unitários
- Regras de domínio testadas isoladamente em `tests/unit/`, sem dependência de banco ou rede — services testados com repositories mockados/fake.

## Dados de teste
- Sem uso de CPF, nome ou documento reais em fixtures — sempre dados sintéticos claramente inválidos como reais (ex. CPFs de teste conhecidos, `000.000.000-00` ou faixas reservadas para teste).

## CI
- Suite de testes (unit + contract) roda no pipeline de CI a cada push; falha de teste ou cobertura abaixo do mínimo bloqueia merge.
