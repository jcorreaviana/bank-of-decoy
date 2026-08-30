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

`GET /internal/chaos/status` (issue #57) é o par de leitura, mesma proteção — retorna o estado **efetivo** do serviço (override em runtime se houver, senão o fallback via variável de ambiente). Existe porque `agent-preditivo` precisava de um jeito confiável de perguntar "o caos está ativo agora?" que refletisse ativações feitas só via `POST` (como o `chaos-orchestrator` faz) — antes disso, `chaos_status.is_chaos_enabled()` só enxergava a variável de ambiente estática via `docker inspect`, nunca o override em runtime, e issues de bug abertas durante uma ativação via `POST` ficavam sem a label `chaos-test`.

```bash
curl http://localhost:8002/internal/chaos/status -H "X-Internal-Token: $CHAOS_INTERNAL_TOKEN"
# {"enabled":true,"failure_rate":1.0,"failure_types":["503"]}
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

### Janela de validação orgânica de 2h (issue #54)

`scripts/validation_window.py` é o runbook operacional descrito em [specs/business/24-camada-caos-avancada.md](specs/business/24-camada-caos-avancada.md), seção "Execução orgânica" — sobe o ambiente **efêmero** (`docker-compose.test.yml`, não o principal: consistente com a decisão de v12/v16 do documento de escopo de não misturar tráfego sintético/caos com o dataset persistente de ML, e com a janela anterior já documentada em [docs/licoes-aprendidas-operacao-real.md](docs/licoes-aprendidas-operacao-real.md), que rodou contra o mesmo compose), aplica as migrations dos 5 bancos, inicia o gerador de tráfego sintético (`scripts/synthetic_traffic.py`) e o `chaos-orchestrator` em ciclos repetidos do cenário de cascata de exemplo, por um tempo de relógio configurável.

```bash
cd scripts
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # (ou .venv/bin/pip fora do Windows)

# janela real de 2h (default) - roda a partir da raiz do repo
CHAOS_INTERNAL_TOKEN=$CHAOS_INTERNAL_TOKEN scripts/.venv/Scripts/python.exe scripts/validation_window.py

# teste curto antes de rodar a janela real
CHAOS_INTERNAL_TOKEN=$CHAOS_INTERNAL_TOKEN scripts/.venv/Scripts/python.exe scripts/validation_window.py --duration-minutes 10
```

O que o script faz, em ordem:

1. `docker compose -f docker-compose.test.yml up -d --build` (pulável com `--skip-up`, para reaproveitar um ambiente já no ar) e espera os 4 serviços responderem `/health`.
2. `alembic upgrade head` nos 5 serviços (`onboarding-service`, `account-service`, `pix-key-service`, `transaction-service`, `agent-ops-service`) — idempotente, seguro rodar sempre. **Sem isso, o ambiente efêmero recém-criado só tem os 5 bancos vazios** (`infra/postgres/init-databases.sh` cria os bancos, não o schema) — toda chamada à API falharia com 500 (`relation does not exist`), silenciosamente o bastante para passar despercebido numa janela inteira de 2h (mesmo achado já registrado em `docs/licoes-aprendidas-operacao-real.md` para a primeira janela, agora automatizado aqui).
3. Tira um snapshot das issues candidatas (label `business-story`/`bug`, sem assignee) que já existiam **antes** da janela começar — usado depois para não confundir backlog antigo com atividade gerada por esta execução.
4. Inicia `synthetic_traffic.py` (roda pela duração inteira da janela, em background) e, em paralelo, `chaos-orchestrator/orchestrator.py` contra `scenarios/account_and_queue_cascade.yaml`, **repetindo o cenário em ciclos** (cada ciclo ~7 min + um intervalo entre ciclos, default 3 min) até o relógio da janela acabar — decisão de repetir em vez de uma única ativação isolada, para gerar volume de sinal suficiente para os agentes ao longo de 2h (uma única cascata de ~7 min deixaria a maior parte da janela sem nenhum estímulo de caos).
5. Ao fim do relógio (ou em `Ctrl+C`, ver abaixo): para de agendar novo ciclo de caos e sinaliza o gerador de tráfego para parar (`stop_traffic.flag`) — **sem** `docker compose down` e **sem** tocar nos daemons dos agentes (`agent-preditivo`, `agent-local`), que são processos externos, iniciados/parados pelo operador, nunca por este script.
6. Espera os agentes terminarem: verifica repetidamente (a cada `--poll-interval-seconds`, default 30s) se ainda existe (a) alguma issue candidata **nova** (criada durante a janela, sem `chaos-test`, sem dependência aberta) ainda sem assignee, ou (b) alguma issue aberta atribuída ao agente local ainda sem PR/decisão (sem a label `agent-stuck`) — reaproveita o filtro real de `agent_local.polling.pick_candidate_issue` (mesmo venv do `agent-local`, para não arriscar essa lógica divergir com o tempo) e a busca `gh` por `assignee:@me`. `agent-stuck` (issues #40/#41) conta como estado terminal — um item escalado não vai se resolver sozinho, então não bloqueia o fim da janela. Só declara a janela finalizada depois que "sem pendência" se mantiver estável por uma janela de estabilização (`--settle-window-seconds`, default: maior intervalo de polling entre `agent-local`/`agent-preditivo` + 60s de margem) — cobre o caso de um agente estar no meio de um ciclo exatamente no instante do corte. Não existe teto artificial que aborte essa espera; se ela demorar muito além do esperado, o script só loga um aviso periódico (`--warn-after-seconds`, default 30min) para o operador investigar manualmente, sem cortar nenhum agente.
7. Imprime um resumo com os pontos exatos para conferir evidência (ver próxima seção) e **encerra sem derrubar o ambiente**.

**Como abortar com segurança no meio da janela**: `Ctrl+C` no terminal onde o script está rodando. O Windows propaga `CTRL_C_EVENT` para todo o console, então o ciclo de caos em andamento (se houver) roda seu próprio desligamento explícito (mesmo mecanismo do `chaos-orchestrator` sozinho, acima) antes de sair; o script grava o `stop_traffic.flag` e segue direto para o passo 6 (espera dos agentes) em vez de sair imediatamente — o ambiente nunca é derrubado e nenhum agente é interrompido por causa do abort. Um segundo `Ctrl+C` durante a própria espera (passo 6) só encerra o script — o ambiente e os agentes continuam rodando por conta própria, sem serem afetados.

### Lançando os daemons (`agent-local` / `agent-preditivo`)

```bash
cd agent-local && .venv/Scripts/python.exe -m agent_local.polling      # loop continuo
cd agent-preditivo && .venv/Scripts/python.exe -m agent_preditivo.polling
```

**Não lance o daemon do `agent-local` como subtarefa em background de uma sessão interativa do Claude Code/VS Code** (achado real, issue #66 - vazamento de isolamento entre o subprocess do SDK e a working tree real do operador). O daemon herda o ambiente de processo de quem o lança; se o lançador for uma sessão interativa do Claude Code, variáveis que identificam essa sessão para o IDE (`CLAUDE_CODE_MESSAGING_SOCKET`/`CLAUDE_CODE_MESSAGING_TOKEN`/`CLAUDE_CODE_SESSION_ID`) são repassadas ao subprocess do Claude Agent SDK que `agent_local.sdk_invocation.invoke_sdk` invoca por issue - o CLI empacotado usa esse canal para se conectar à sessão IDE ativa, fazendo Read/Edit resolverem contra a workspace real aberta no VS Code em vez do clone isolado (`agent-local/workspace/bank-of-decoy`) passado via `cwd`. `sdk_invocation.py` já reduz o ambiente do subprocess a uma lista positiva de variáveis (`_minimal_subprocess_env`, issue #66) como correção primária - mas rodar o daemon a partir de um terminal/serviço limpo, sem essa ancestralidade, é defesa em profundidade: reduz a superfície de qualquer variável nova que amanhã carregue o mesmo tipo de canal ambiente, sem depender só da lista de `_ALLOWED_ENV_PASSTHROUGH` estar completa.

Antes de confiar num lançamento novo do daemon (versão nova do `claude_agent_sdk`/CLI, forma diferente de iniciar o processo), rode o teste de regressão real de isolamento:

```bash
cd agent-local && .venv/Scripts/python.exe -m pytest tests/integration/test_isolation_leak.py -v
```

(faz uma chamada real ao SDK - custa uso de API, não roda com a suíte rápida de `tests/unit/`.)

### Onde encontrar as evidências ao final da janela

O resumo impresso ao final já traz os comandos prontos; os mesmos pontos, para referência:

- **Grafana** (`admin`/`admin`): `http://localhost:3000/d/fase1-golden-signals` (golden signals) e `http://localhost:3000/d/metricas-negocio-v1` (métricas de negócio) — golpe visual da rampa de `degradacao_progressiva`, taxa de erro, latência p95 durante os ciclos de caos.
- **Postgres `agent_ops`**: `docker exec bank-of-decoy-postgres psql -U bank -d agent_ops -c "SELECT * FROM risk_decisions ORDER BY decided_at;"` e o mesmo para `flagged_signals` — decisões do agente local e sinais deduplicados do agente preditivo durante a janela.
- **Issues no GitHub**: `gh issue list --search "created:>=<data> label:business-story,bug,chaos-test"` — inclui as issues `chaos-test` (esperado que fiquem sem PR, o agente local as ignora de propósito) e as issues reais de bug/oportunidade abertas a partir dos sinais da janela.
- **Logs estruturados dos serviços**: `docker compose -f docker-compose.test.yml logs --since <inicio-da-janela> <servico>` (JSON de uma linha, `specs/tech/logging.md`).
- **Logs desta execução**: `scripts/validation_window_logs/<timestamp>/` — log do gerador de tráfego e de cada ciclo do `chaos-orchestrator`.

Testes em `scripts/tests/test_validation_window.py` cobrem só a lógica pura (decisão de "há pendência?", leitura de intervalo do `.env`) com `pytest`, sem depender de `gh`/Docker reais — a parte que fala com o mundo real foi validada manualmente contra o ambiente e o GitHub reais (ambiente efêmero + uma issue de teste real criada/atribuída/fechada para confirmar a detecção, depois removida).
