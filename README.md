# Bank of Decoy

Monorepo de microserviços (`onboarding-service`, `account-service`, `pix-key-service`, `transaction-service`) com Postgres, Kafka, Prometheus e Grafana como infraestrutura compartilhada. Specs do projeto em [specs/](specs/).

## Configuração inicial

Antes de subir qualquer um dos ambientes abaixo, copie `.env.example` para `.env` na raiz e preencha `CPF_ENCRYPTION_KEY` com uma chave real (gere com `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) — `docker-compose.yml`/`docker-compose.test.yml` leem esse arquivo automaticamente. `.env` nunca é commitado (specs/tech/security.md, specs/business/18-correcao-vazamento-chave.md).

## Ambientes de desenvolvimento local

Existem dois arquivos de compose na raiz, e eles **não rodam em paralelo** — ambos usam as mesmas portas:

- `docker-compose.yml`: ambiente principal, com volume nomeado persistente para o Postgres (`postgres_data`). Dados sobrevivem a `docker-compose down`/`up`.
- `docker-compose.test.yml`: ambiente efêmero, idêntico ao principal exceto que o Postgres **não** tem volume nomeado — cada `up` começa com bancos vazios (migrations rodam do zero). Útil para testes de ponta a ponta que não podem depender de estado deixado por execuções anteriores.

### Alternar entre os dois

Antes de subir um, derrube o outro:

```bash
# do principal para o de teste
docker-compose down
docker-compose -f docker-compose.test.yml up -d

# de volta ao principal
docker-compose -f docker-compose.test.yml down
docker-compose up -d
```

`docker-compose down` sem `-v` preserva o volume `postgres_data` do ambiente principal — os dados persistentes não são afetados por um ciclo no ambiente de teste.

## Camada de caos (Fase 2)

Cada um dos 4 microserviços tem um middleware de injeção de falha (`shared/chaos`), desligado por padrão. Toggle independente por serviço via 3 variáveis de ambiente lidas dentro do container: `CHAOS_ENABLED`, `CHAOS_FAILURE_RATE` (0.0–1.0) e `CHAOS_FAILURE_TYPES` (lista separada por vírgula entre `timeout`, `503`, `500`, `latencia`). Ver [specs/business/11-camada-caos.md](specs/business/11-camada-caos.md) para o desenho completo.

No `docker-compose.yml`/`docker-compose.test.yml`, essas variáveis são preenchidas a partir de vars com prefixo por serviço no host (`ONBOARDING_`, `ACCOUNT_`, `PIX_KEY_`, `TRANSACTION_`), para permitir ligar o caos num serviço sem afetar os outros:

```bash
# liga caos so no transaction-service, 50% das requisicoes, so 503/500
export TRANSACTION_CHAOS_ENABLED=true
export TRANSACTION_CHAOS_FAILURE_RATE=0.5
export TRANSACTION_CHAOS_FAILURE_TYPES=503,500
docker compose up -d --force-recreate transaction-service

# desliga de novo (volta ao padrao: desligado)
unset TRANSACTION_CHAOS_ENABLED TRANSACTION_CHAOS_FAILURE_RATE TRANSACTION_CHAOS_FAILURE_TYPES
docker compose up -d --force-recreate transaction-service
```

Prefixos disponíveis: `ONBOARDING_CHAOS_*`, `ACCOUNT_CHAOS_*`, `PIX_KEY_CHAOS_*`, `TRANSACTION_CHAOS_*`.

`/health` e `/metrics` nunca sofrem injeção (senão o healthcheck do compose e o scrape do Prometheus, usados para observar o efeito do caos, ficariam cegos junto).

Logs de falha injetada carregam `context.chaos_injected: true` (ver [specs/tech/logging.md](specs/tech/logging.md)) — usado pelo agente preditivo (Fase 3) para não confundir caos com bug real.
