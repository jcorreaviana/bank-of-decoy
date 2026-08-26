# Testing

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
