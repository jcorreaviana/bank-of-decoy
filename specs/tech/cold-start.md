# Cold start do ambiente de validação

Automação do cold start do ambiente efêmero de validação (`docker-compose.test.yml`) — issue #81. Antes desta spec, subir o ambiente era uma operação manual multi-terminal: um terminal para `docker compose up`, acompanhando os logs manualmente para saber quando cada serviço tinha ficado pronto; cinco terminais (um por serviço) para rodar `alembic upgrade head` na pasta certa de cada um; e mais dois terminais — um por daemon (`agent-local`, `agent-preditivo`) — exigindo que o operador lembrasse, a cada vez, de não lançá-los como subtarefa de uma sessão Claude Code/VS Code (achado real, issues #66/#86).

## Visão geral

Um único script, `scripts/cold_start.py`, substitui essa operação:

```
scripts/.venv/Scripts/python.exe scripts/cold_start.py
```

Ele faz, em ordem, e falha rápido e claro em qualquer etapa:

1. `docker compose -f docker-compose.test.yml up -d --build`.
2. Espera **health check real** de cada peça do ambiente (nunca um sleep fixo) — ver "Health check real" abaixo.
3. Aplica as 5 migrations, cada uma rodando de **dentro da pasta do próprio serviço** — ver "Migrations sem cwd ambíguo" abaixo.
4. Inicia os dois daemons dos agentes via Scheduled Task do Windows — ver "Isolamento estrutural dos daemons" abaixo.

Flags (`--no-build`, `--skip-up`, `--skip-migrations`, `--skip-daemons`, `--health-timeout-seconds`) permitem reaproveitar partes de uma execução anterior — mesma convenção já usada por `scripts/validation_window.py` (issue #54).

A lógica de subida/health-check/migrations foi extraída para `scripts/environment_bootstrap.py`, compartilhado entre `cold_start.py` e `validation_window.py` — evita duplicar essa lógica nos dois scripts e o risco de divergirem com o tempo (mesmo racional das decisões v11/v38 do documento de escopo). `validation_window.py` foi refatorado para reusar esse módulo em vez de manter sua própria cópia.

## Health check real

Um `sleep` fixo não é health check — some serviços demoram mais que outros para ficar prontos, e um `sleep` grande o bastante para o pior caso desperdiça tempo no caso comum, enquanto um `sleep` pequeno demais falha de forma não determinística. `environment_bootstrap.wait_for_healthy` faz uma chamada de rede real e barata por componente, repetida a cada `--poll-interval-seconds` até um timeout configurável, e falha com `SystemExit` nomeando exatamente quais componentes ficaram pendentes se o timeout for atingido:

| Componente | Mecanismo do check |
|---|---|
| `onboarding-service`, `account-service`, `pix-key-service`, `transaction-service` | `GET /health` (HTTP 200) |
| `prometheus` | `GET /-/ready` (HTTP 200) |
| `grafana` | `GET /api/health` (HTTP 200) |
| `kafka` | conexão TCP na porta do listener exposto ao host (29092) |
| Postgres — `onboarding`, `account`, `pix_key`, `transaction`, `agent_ops` | conexão via `psycopg2` + `SELECT 1` em **cada um dos 5 bancos** |

`agent_ops` não é um container HTTP próprio (`agent-ops-service/` só contém as migrations — não há serviço FastAPI implantado para ele, ver `docker-compose.test.yml`), mas a issue #81 pede health check dele explicitamente. Conectar diretamente no banco `agent_ops` é o check real equivalente — e é estritamente mais correto do que confiar só no healthcheck nativo do container Postgres (que só confirma que o servidor aceita conexão no banco administrativo `bank`, não que os 5 bancos de domínio foram de fato criados por `infra/postgres/init-databases.sh`; uma falha parcial nesse script deixaria o healthcheck do container "saudável" mesmo com um banco faltando).

**Decisão: checks do lado do host (Python), não `healthcheck:` nativo no `docker-compose.test.yml`.** Considerado e descartado — usar blocos `healthcheck:` do Compose + `docker compose up --wait` delegaria a espera ao próprio Docker, mas exigiria que cada imagem (Kafka, Prometheus, Grafana — nenhuma controlada por este projeto) tivesse `curl`/`wget` disponível internamente para o comando do healthcheck, o que não é garantido (`python:3.12-slim`, base dos 4 serviços de domínio, nem tem `curl` por padrão). Checks do lado do host reusam o padrão já validado em produção por `validation_window.py` (10+ execuções reais documentadas no changelog), ficam inteiramente em Python testável (ver "Testes"), e não dependem de nenhuma imagem de terceiro ter a ferramenta certa embutida.

## Migrations sem cwd ambíguo

Achado da issue #75: `chaos-orchestrator/orchestrator.py` era invocado com `cwd=chaos-orchestrator/`, mas um argumento `--scenario` relativo era resolvido contra a raiz do repo por quem chamava — o subprocesso então via esse caminho relativo como `chaos-orchestrator/chaos-orchestrator/scenarios/...`, inexistente, e todos os 40 ciclos da janela real de 2h falharam silenciosamente do mesmo jeito. Lição generalizada aqui: **nunca deixar caminho ambíguo entre o cwd do script e o cwd esperado por cada subcomando.**

`environment_bootstrap.migration_commands()` gera, para cada um dos 5 serviços, um `MigrationCommand` com `cwd=REPO_ROOT/<pasta-do-serviço>` explícito — nunca a raiz do repo, nunca `-c <caminho>` do alembic apontando de fora. `run_migrations()` roda `<venv-do-serviço>/python.exe -m alembic upgrade head` com esse `cwd`, e `DATABASE_URL` apontando para o banco daquele serviço. Falha no primeiro serviço que falhar (não continua tentando os seguintes), com uma mensagem nomeando exatamente o serviço, o banco e o `cwd` usado — nunca uma ambiguidade sobre onde a migration rodou.

## Isolamento estrutural dos daemons

Até esta issue, o README só recomendava por escrito não lançar `agent-local` como subtarefa em background de uma sessão Claude Code/VS Code (achado real, issues #66/#86 — vazamento de isolamento entre o subprocess do Claude Agent SDK e a working tree real do operador, corrigido no código por duas vezes: variável de ambiente herdada e, depois, arquivo de lock de sessão IDE lido do disco). Essa recomendação dependia inteiramente da disciplina do operador lembrar dela a cada cold start — exatamente o tipo de operação manual que esta issue pede para eliminar por design, não por disciplina.

### Decisão: Scheduled Task do Windows

Duas opções foram avaliadas:

- **Scheduled Task do Windows** (escolhida) — o processo real do daemon é criado pelo serviço Task Scheduler (`svchost`), nunca como filho direto de quem disparou `schtasks /run`. O ambiente do processo filho vem do registro (`HKCU\Environment`), não da árvore de processos de quem chamou `/run` — **mesmo que esse chamador seja o próprio terminal integrado de uma sessão Claude Code/VS Code**. O isolamento vale estruturalmente, independente de onde/como o cold start foi disparado.
- **`.bat` clicável no Explorer** — descartada como mecanismo primário. Também alcança isolamento real (duplo clique no Explorer gera `cmd.exe` como filho de `explorer.exe`, fora de qualquer árvore de sessão IDE), mas **só se o operador de fato clicar no arquivo** — rodar esse mesmo `.bat` de dentro de um terminal integrado do VS Code (engano fácil, especialmente vindo de um fluxo que já usa terminal para tudo o mais) reabriria exatamente a classe de vazamento que a #66/#86 corrigiram. Depende de disciplina no passo de disparo, o que a issue pede para evitar.

Scheduled Task também resolve, de graça, dois problemas operacionais que um `.bat` não resolveria sozinho: `ExecutionTimeLimit` do Task Scheduler tem um teto padrão de 72h (mataria um daemon de polling contínuo pensado para rodar indefinidamente — `register_daemon_task.ps1` seta explicitamente `[TimeSpan]::Zero`), e `RestartCount`/`RestartInterval` reinicia o daemon sozinho se ele cair por uma exceção não tratada escapando do loop de polling.

### Implementação

- `scripts/register_daemon_task.ps1` — registra (idempotente, `-Force`) uma Scheduled Task sem nenhum Trigger (não roda em horário nenhum — só sob demanda), com `LogonType Interactive`/`RunLevel Limited` (roda com o perfil do usuário atual — credenciais do `gh` CLI, acesso ao Ollama local — sem precisar armazenar senha).
- `scripts/daemon_tasks.py` — orquestra em Python: `task_exists()` (via `schtasks /query`), `register()` (invoca o `.ps1` acima) e `start()` (`schtasks /run`), registrando a task só na primeira vez (cold starts seguintes não recriam). `DAEMON_TASKS` define as duas tasks: `BankOfDecoy-AgentLocal` (`agent-local/`, `agent_local.polling`) e `BankOfDecoy-AgentPreditivo` (`agent-preditivo/`, `agent_preditivo.polling`) — cada uma com `WorkingDirectory` apontando para a pasta do próprio daemon, nunca a raiz do repo (mesmo princípio da issue #75 aplicado aqui).
- `scripts/cold_start.py` chama `daemon_tasks.start_all()` como última etapa (pulável com `--skip-daemons`).

### Pré-requisito: `.env` de cada daemon precisa ser real (issue #81, achado colateral)

Nenhum dos dois daemons carregava `agent-local/.env`/`agent-preditivo/.env` automaticamente antes desta issue — `get_settings()` só lia `os.environ` direto, então qualquer variável do `.env` só valia se o operador a exportasse manualmente no terminal antes de iniciar o daemon (mais um passo manual escondido dentro do fluxo que esta issue elimina). Isso é inviável sob Scheduled Task: o processo nasce com o ambiente do registro do usuário, nunca com o que foi exportado numa sessão de terminal específica.

Corrigido adicionando `python-dotenv` (`agent_local/config.py`, `agent_preditivo/config.py`): `get_settings()` agora chama `load_dotenv(_ENV_FILE, override=False)` antes de ler `os.environ` — `_ENV_FILE` é derivado do próprio módulo (`Path(__file__).resolve().parent.parent / ".env"`), não do cwd de quem inicia o processo, mesmo princípio já usado por `logging_config.py` para o caminho de `daemon.log` (issue #79). `override=False` garante que uma variável já presente no ambiente do processo sempre vence o `.env`, nunca o contrário.

**Consequência operacional**: `agent-local/.env` já existe com valores reais. `agent-preditivo/.env` **não existe ainda** — só `agent-preditivo/.env.example`. Antes de depender do cold start para lançar `agent-preditivo` com funcionalidade completa (`CHAOS_INTERNAL_TOKEN` real para o endpoint de leitura de estado de caos, issue #57; `DISCORD_WEBHOOK_URL` real para notificações), copie `agent-preditivo/.env.example` para `agent-preditivo/.env` e preencha os dois segredos com os mesmos valores já usados no `.env` da raiz do repo. Sem isso, o daemon ainda inicia e funciona (`CHAOS_INTERNAL_TOKEN` ausente cai no fallback documentado pela v49 do changelog — `docker inspect` na variável de ambiente estática, não no override em runtime — e notificações Discord simplesmente não saem), só não com a funcionalidade completa. Este é um passo único de configuração de segredo, não uma operação repetida a cada cold start — por isso não foi automatizado neste script (um script não deveria materializar segredos reais em nome do operador).

### Como parar os daemons

`schtasks /end /tn BankOfDecoy-AgentLocal` / `schtasks /end /tn BankOfDecoy-AgentPreditivo` (ou pela GUI do Agendador de Tarefas). Como antes desta issue, o cold start nunca para os daemons sozinho — eles continuam rodando até o operador decidir parar.

## Testes

`scripts/tests/test_environment_bootstrap.py` e `scripts/tests/test_daemon_tasks.py` cobrem a lógica de orquestração pura, sempre com um `runner`/relógio falso no lugar de `subprocess.run`/`time.sleep` reais — sem precisar de Docker, Postgres, Kafka, PowerShell ou Task Scheduler reais rodando:

- `wait_for_healthy`: sucesso quando todo check fica saudável antes do timeout; um check que levanta exceção conta como "ainda não saudável" sem derrubar o loop; timeout falha com `SystemExit` nomeando exatamente os componentes pendentes; cobertura dos 9 componentes exigidos pela issue (protege contra um check ser removido em silêncio no futuro).
- `migration_commands`/`run_migrations`: cada comando usa `cwd=pasta-do-próprio-serviço` (nunca a raiz do repo); falha rápido no primeiro serviço que falhar, identificando serviço/banco/cwd na mensagem; não tenta os serviços seguintes após uma falha.
- `docker_compose_up`: inclui/omite `--build` conforme pedido; falha rápido se o comando falhar.
- `daemon_tasks.register_command`/`start_command`: comandos puros (sem I/O), `-WorkingDirectory` sempre a pasta do daemon; `start()` só registra a task na primeira vez (idempotente), dispara `schtasks /run` depois, falha rápido e claro se registro ou disparo falharem.
- `agent-local/tests/unit/test_config.py`, `agent-preditivo/tests/unit/test_config.py`: variável do `.env` é lida quando ausente do ambiente; variável já no ambiente vence o `.env`; ausência do `.env` cai nos defaults normalmente.

O que **não** é coberto por teste automatizado (Docker/Task Scheduler reais não fazem sentido em CI, mesmo racional já usado por `validation_window.py`): subida real dos containers, um check de rede batendo contra um serviço real, e o processo do daemon de fato nascendo sem ancestralidade de sessão IDE sob uma Scheduled Task real — validado manualmente, ver próxima seção.

## Validação

Ambiente derrubado do zero (`docker compose -f docker-compose.test.yml down`, sem `--volumes` — ver nota abaixo) e `scripts/cold_start.py` rodado sem nenhum passo manual do operador. Evidência real registrada em `docs/escopo-arquitetura.md` (changelog desta issue).

**Nota sobre o volume do Postgres**: `docker-compose.test.yml` não declara volume nomeado para o Postgres (por desenho — v12/v16 do documento de escopo: ambiente efêmero, sem persistência). Um volume nomeado `bank-of-decoy_postgres_data` foi encontrado anexado ao container em produção real durante esta validação, com o dataset de ML completo (500k+ linhas) — leftover de uma sessão anterior, não coberto por nenhuma declaração do `docker-compose.test.yml` atual. `down` (sem `-v`) preserva esse volume intacto e órfão no disco; `cold_start.py` sobe um Postgres novo sem essa volume anexada (efêmero, como pretendido). Confirmar com o operador antes de qualquer `down --volumes`/`docker volume rm` nesse volume especificamente — não é gerenciado por este script.
