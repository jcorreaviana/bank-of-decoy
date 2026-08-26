# Infrastructure

## docker-compose local
Um `docker-compose.yml` na raiz do repositório sobe a infraestrutura compartilhada de desenvolvimento local:
- Postgres (um container; cada serviço usa seu próprio banco/schema dentro dele — ver [database.md](database.md)).
- Kafka.
- Zookeeper, se a versão do Kafka usada exigir (não necessário em modo KRaft).

Os microserviços em si (onboarding, account, pix-key, transaction) podem rodar fora do compose (venv local, ver [stack.md](stack.md)) apontando para essa infraestrutura, ou ser adicionados ao mesmo compose conforme o projeto evoluir.

## Portas padrão dos serviços

| Serviço              | Porta |
|-----------------------|-------|
| onboarding-service    | 8001  |
| account-service        | 8002  |
| pix-key-service        | 8003  |
| transaction-service    | 8004  |

## Variáveis de ambiente
- Cada serviço documenta suas variáveis de ambiente em um `.env.example` próprio (ver [security.md](security.md)), incluindo no mínimo:
  - `DATABASE_URL`
  - `KAFKA_BOOTSTRAP_SERVERS`
  - `SERVICE_NAME`
  - `LOG_LEVEL`
  - `PORT`
- Nenhum valor real (senha, host de produção) entra em `.env.example` — apenas placeholders (ex. `postgresql://user:password@localhost:5432/onboarding`).
