# 01 — Setup do monorepo

## Contexto / objetivo
Estabelecer o esqueleto do monorepo com os quatro microserviços da Fase 1, cada um bootando de forma independente e respondendo a um health check. Esta é a base sobre a qual todas as histórias seguintes constroem — sem ela, nenhuma outra spec pode ser implementada.

## Contrato afetado
- `GET /health` em cada um dos quatro serviços (não versionado com `/v1/` — é infraestrutura, não recurso de domínio).
  - Resposta 200: `{ "status": "ok" }`.

## Escopo
Criar, na raiz do repositório, um diretório por serviço:
- `onboarding-service/`
- `account-service/`
- `pix-key-service/`
- `transaction-service/`

Cada diretório segue a estrutura de pastas definida em [stack.md](../tech/stack.md) (`app/`, `app/routers/`, `app/models/`, `app/schemas/`, `app/services/`, `app/repositories/`, `app/core/`, `tests/`), com:
- `app/main.py` criando a app FastAPI e registrando ao menos o router de health.
- Ambiente virtual próprio e `requirements.txt` com as dependências mínimas de [stack.md](../tech/stack.md) (FastAPI, Uvicorn, SQLAlchemy, psycopg2-binary, pytest).
- `.env.example` com as variáveis mínimas listadas em [infrastructure.md](../tech/infrastructure.md) (`DATABASE_URL`, `KAFKA_BOOTSTRAP_SERVERS`, `SERVICE_NAME`, `LOG_LEVEL`, `PORT`).
- `Dockerfile` mínimo para rodar o serviço via Uvicorn.

`docker-compose.yml` na raiz do repositório subindo Postgres e Kafka (+ Zookeeper se necessário), conforme [infrastructure.md](../tech/infrastructure.md).

## Critério de aceite
- [ ] Os quatro diretórios de serviço existem com a estrutura de pastas de [stack.md](../tech/stack.md).
- [ ] Cada serviço sobe localmente (`uvicorn app.main:app`) na porta definida em [infrastructure.md](../tech/infrastructure.md) (8001/8002/8003/8004) sem erro.
- [ ] `GET /health` em cada serviço retorna 200 com `{ "status": "ok" }`.
- [ ] `docker-compose up` na raiz sobe Postgres e Kafka acessíveis localmente.
- [ ] Cada serviço tem `.env.example` versionado e `.env` no `.gitignore`.
- [ ] Nenhum serviço tem dependência de path relativo para outro serviço (ambientes virtuais isolados).

## Specs técnicas aplicáveis
- [stack.md](../tech/stack.md) — estrutura de pastas, dependências, ambiente virtual.
- [infrastructure.md](../tech/infrastructure.md) — docker-compose, portas, variáveis de ambiente.
