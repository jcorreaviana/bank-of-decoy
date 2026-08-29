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

### Ajuste em runtime (Fase 2b)

Desde a issue #51 ([specs/business/24-camada-caos-avancada.md](specs/business/24-camada-caos-avancada.md)), as 3 variáveis acima passam a ser só a config inicial/fallback: cada serviço expõe `POST /internal/chaos/config`, que ajusta tipo(s) de falha, taxa e uma duração/janela opcional **sem restart do processo** (estado em memória, por serviço, perdido ao reiniciar o container).

Esse endpoint não é exposto publicamente — protegido por um segredo compartilhado (`CHAOS_INTERNAL_TOKEN`, igual nos 4 serviços, mesmo padrão de `CPF_ENCRYPTION_KEY`) enviado no header `X-Internal-Token`. Sem essa variável configurada, o endpoint fica inacessível (fail closed).

```bash
# liga caos so no account-service, 100% das requisicoes, so 503, por 5 minutos -
# sem precisar de --force-recreate
curl -X POST http://localhost:8002/internal/chaos/config \
  -H "Content-Type: application/json" \
  -H "X-Internal-Token: $CHAOS_INTERNAL_TOKEN" \
  -d '{"enabled": true, "failure_rate": 1.0, "failure_types": ["503"], "duration_seconds": 300}'
```

### Novos tipos de falha (issue #52)

Além de `timeout`/`503`/`500`/`latencia` (constantes), a Fase 2b adiciona 4 tipos com parâmetros próprios, ajustáveis no mesmo `POST /internal/chaos/config`:

- `degradacao_progressiva`: latência HTTP que cresce de 0 até `ramp_ceiling_seconds` ao longo de `ramp_window_seconds` desde a ativação — diferente de `latencia` (constante), testa detecção de tendência, não só limiar.
- `payload_corrompido_sutil`: corrompe silenciosamente um campo específico da resposta de rotas conhecidas (ex. `saldo` vira string em `GET /v1/accounts/{id}`, `ativa` é forçado a `true` em `GET /v1/pix-keys/lookup`) — passa validação, propaga inconsistência sem erro explícito.
- `kafka_lag` (só no `account-service`, consumer de `onboarding.aprovado`): atraso crescente antes de processar cada mensagem afetada, `lag_increment_ms` por vez até `lag_ceiling_ms` — nunca para de consumir, simula backlog.
- `kafka_delay` (só no `onboarding-service`, producer): atraso fixo `kafka_delay_seconds` antes de cada publish — simula latência da infraestrutura de mensageria.

```bash
# rampa de latencia de 0 a 2s em 60s no account-service
curl -X POST http://localhost:8002/internal/chaos/config \
  -H "Content-Type: application/json" \
  -H "X-Internal-Token: $CHAOS_INTERNAL_TOKEN" \
  -d '{"enabled": true, "failure_rate": 1.0, "failure_types": ["degradacao_progressiva"], "ramp_ceiling_seconds": 2.0, "ramp_window_seconds": 60}'
```

Sem `duration_seconds`, o override vale até o próximo `POST` ou até o processo reiniciar (nesse caso as variáveis de ambiente voltam a valer como fallback).

### Cascata coordenada (`chaos-orchestrator`, issue #53)

`chaos-orchestrator/` é um runner Python standalone (fora dos 4 microserviços, sem framework web) que lê um cenário YAML descrevendo uma **timeline** de ativações de caos em múltiplos serviços e chama `POST /internal/chaos/config` de cada um no minuto certo — permite simular cascata (ex. um serviço degradando enquanto sua fila de mensagens também atrasa) sem coordenação manual.

```bash
cd chaos-orchestrator
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # (ou .venv/bin/pip fora do Windows)

# contra o ambiente local (docker-compose up ou docker-compose.test.yml) já no ar
CHAOS_INTERNAL_TOKEN=$CHAOS_INTERNAL_TOKEN .venv/Scripts/python orchestrator.py scenarios/account_and_queue_cascade.yaml
```

Formato do cenário (`scenarios/account_and_queue_cascade.yaml` é o exemplo de referência): `timeline` é uma lista de passos, cada um com `service`, `failure_types`, `start_minute`/`duration_minutes` (relativos ao início da execução do orquestrador) e `params` (os mesmos campos aceitos pelo payload da API — `failure_rate`, `ramp_ceiling_seconds`, `lag_increment_ms`, `kafka_delay_seconds` etc.).

```yaml
timeline:
  - service: account-service
    failure_types: [degradacao_progressiva]
    start_minute: 2
    duration_minutes: 5
    params:
      failure_rate: 1.0
      ramp_ceiling_seconds: 3.0
      ramp_window_seconds: 240
```

Comportamento:
- Cada ativação já sai com um `duration_seconds` de segurança (janela prevista + margem) — mesmo que o orquestrador seja interrompido de forma abrupta (`SIGKILL`, queda de máquina), o serviço se auto-desliga sozinho depois de um tempo, sem depender do orquestrador terminar corretamente.
- `Ctrl+C` (`SIGINT`/`SIGTERM`) interrompe a timeline o quanto antes e dispara desligamento explícito de tudo que estiver ativo naquele momento.
- Falha de rede/timeout ao chamar um serviço específico é logada (nível `ERROR`) e não derruba o restante da timeline — o orquestrador segue tentando os próximos passos.
- Duas ativações que se sobrepõem no **mesmo** serviço são fundidas numa única chamada (o endpoint substitui `failure_types` por completo a cada `POST` — duas chamadas independentes fariam a segunda apagar a primeira).
- Todo log segue o formato de linha única JSON de [specs/tech/logging.md](specs/tech/logging.md), com `trace_id` único por execução do cenário — evidência para a janela de validação da issue #54 e para o artigo.

Testes em `chaos-orchestrator/tests/` (`pytest`, sem precisar do ambiente Docker no ar — timeline exercitada com relógio falso, sem esperar minutos reais).
