# Relatório da janela de validação real de 2h — Fase 2b

**Janela:** 2026-08-30, ~13:16 UTC (ambiente efêmero criado) a 15:29 UTC (última amostra de tráfego) — script `scripts/validation_window.py`, execução `20260830T132541Z`, `docker-compose.test.yml`, cenário `chaos-orchestrator/scenarios/account_and_queue_cascade.yaml`, isolamento de daemons validado (ver seção 1).

**Fontes de evidência:** banco `agent_ops` (Postgres, tabelas `risk_decisions`/`flagged_signals`), GitHub (issues/PRs/comentários via `gh`), Prometheus (consultas diretas à API `/api/v1/query_range`, mesmas queries de `agent_preditivo/prometheus_client.py`), `daemon.log` de ambos os agentes (cobertura parcial — ver aviso na seção 1), logs do próprio `validation_window.py` (`chaos_cycle_*.log`, `synthetic_traffic.log`), e inspeção direta dos clones de trabalho (real e isolado) e containers Docker.

Nenhum número neste relatório é estimado — todo valor é uma consulta direta a uma dessas fontes, citada inline.

---

## Aviso crítico que muda a leitura de várias seções abaixo: o caos nunca foi injetado

Antes de qualquer outra coisa: **os 40 ciclos do `chaos-orchestrator` ao longo da janela de 2h falharam de forma idêntica, um a um**, com o mesmo erro em `scripts/validation_window_logs/20260830T132541Z/chaos_cycle_01.log` até `chaos_cycle_40.log`:

```
FileNotFoundError: [Errno 2] No such file or directory: 'chaos-orchestrator\scenarios\account_and_queue_cascade.yaml'
```

**Causa raiz, e é minha (do assistente) responsabilidade**: o comando que passei para você rodar `validation_window.py` incluía `--scenario chaos-orchestrator\scenarios\account_and_queue_cascade.yaml` — um caminho relativo à raiz do repo. Mas `run_chaos_cycle` invoca `orchestrator.py` com `cwd=CHAOS_ORCHESTRATOR_DIR` (`scripts/validation_window.py`), ou seja, o subprocesso já está DENTRO de `chaos-orchestrator/`. O caminho relativo que passei virou, na prática, uma tentativa de abrir `chaos-orchestrator/chaos-orchestrator/scenarios/...` — que nunca existiu. O default do próprio script (`DEFAULT_SCENARIO`, um `Path` absoluto) não tem esse problema; a falha só ocorreu porque sobrepus o default com um argumento explícito relativo.

**Consequência prática, confirmada contra o Prometheus (seção 8):** nenhum dos 4 serviços recebeu `degradacao_progressiva` ou `kafka_delay` em nenhum momento da janela — o endpoint `POST /internal/chaos/config` nunca foi chamado. Isso significa que:

- Os 4 sinais `latencia_alta` (issues #69–#72) **não foram causados por caos injetado**. São artefato real de partida a frio (baseline histórica calculada com poucas amostras logo após o ambiente subir, contra o primeiro pico de latência real assim que o tráfego começa) — o mesmo padrão que `docs/licoes-aprendidas-operacao-real.md` e o comentário de auditoria da #62 (sessão anterior) já haviam documentado como classe conhecida de falso positivo.
- As seções 7, 8 e 9 abaixo precisam ser lidas como "o que aconteceu na ausência de caos", não como validação do cenário de cascata em si. O cenário de cascata (#53/#54) **não foi exercitado nesta janela**.
- Isso não invalida o resto da janela: os dois agentes rodaram por 2h reais, processaram sinais reais (mesmo que de origem diferente da esperada), e a mecânica de detecção → decisão → gate funcionou de ponta a ponta. Mas o artigo/documentação não deve alegar "validamos o cenário de cascata sob caos" — isso não ocorreu hoje.

Recomendação: reexecutar a janela (ou só o `chaos-orchestrator` isolado) com `--scenario` omitido (usa o default absoluto) ou com um caminho absoluto explícito, antes de considerar o cenário de cascata validado.

---

## 1. Isolamento dos daemons — evidência e comparação antes/depois da #66

**O que eu NÃO consigo confirmar de forma direta:** `agent-local/daemon.log` e `agent-preditivo/daemon.log` não são escritos pela aplicação (`logging_config.py` usa só `StreamHandler(sys.stdout)` — o nome `daemon.log` é convenção do operador redirecionando stdout no terminal). Os dois arquivos têm o último byte escrito às `2026-08-30T01:29:49Z` / `01:59:33Z` — a sessão de investigação de ontem, terminada ~11h antes desta janela começar. **Os dois daemons relançados hoje em terminais limpos não estão gravando em `agent-local/daemon.log`/`agent-preditivo/daemon.log`** (a saída deles está indo só para os terminais onde rodam, não capturada em arquivo). Isso significa que não tenho o log linha-a-linha de hoje para citar diretamente — a evidência de isolamento abaixo vem de fontes indiretas, mas é real e cruzada contra timestamps precisos.

**Evidência positiva de isolamento (maioria dos casos):**
- Containers Docker criados às `13:16:56Z` (verificado via `docker inspect`), todos os 4 serviços de domínio + Postgres + Kafka — ambiente efêmero genuinamente novo para esta janela.
- `agent_ops` (Postgres) começou vazio nesse mesmo instante — as 8 linhas em `risk_decisions` são 100% desta janela, sem resíduo de sessões anteriores.
- Das 10 issues processadas nesta janela, **7 tiveram diffs corretamente aplicados só no clone isolado** (`agent-local/workspace/bank-of-decoy`), sem tocar a working tree real: `#61` (branch órfã só no clone isolado), `#71` (branch `agent-local/issue-71` e PR limpos), `#62` (PR aberto e mergeado só através do clone isolado — confirmado via `git log` do clone isolado mostrando o commit do fix), `#55`, `#60`, `#68`, `#72` (sem diff, `no_action_needed`).

**Evidência de vazamento real, hoje — comparação direta com o antes/depois da #66:**

A #66 (fechada ontem, `097cb67`) corrigiu o vazamento de variáveis de ambiente de sessão IDE que fazia o CLI empacotado do SDK resolver `Read`/`Edit` contra a working tree real em vez do `cwd` explícito. A correção reduz a *causa* mais comum do vazamento, mas **não é uma garantia geral contra qualquer erro do próprio modelo em relação a qual diretório ele está editando** — e isso se confirmou hoje, de duas formas distintas:

| Issue | O que aconteceu | Evidência |
|---|---|---|
| **#69** (onboarding-service) | O próprio modelo relatou, no comentário da issue: *"inicialmente editei o mirror errado no caminho externo `C:\study\bank-of-decoy`, por engano, e me corrigi via `git rev-parse --show-toplevel`, refazendo as edições no repositório certo"*. **Auto-detectado, mas a correção foi incompleta**: os arquivos da tentativa errada (`onboarding-service/app/core/kafka.py`, `onboarding_events.py`, testes, `docs/escopo-arquitetura.md` v50) ficaram modificados na working tree REAL com `mtime` de `13:55:59`–`13:56:59Z`, e nunca foram revertidos. |
| **#70** (account-service) | Nenhuma menção a erro de diretório no comentário — mas `account-service/app/repositories/account_repository.py` está modificado na working tree REAL, com `mtime` `13:48:11Z`, a 28s do `decided_at` (`13:48:39Z`) registrado no banco. Conteúdo do diff bate exatamente com o que o comentário da #70 descreve (`defer(Account.cpf)`). **Vazamento não detectado pelo próprio agente desta vez.** |
| **#59** (onboarding-service) | Mesmo padrão: `onboarding-service/app/models/onboarding.py` e a migration `1d50cdcec934_add_cpf_hash_and_encrypt_cpf_at_rest.py` estão modificados na working tree REAL, `mtime` `14:12:20`–`14:12:25Z`, ~30s antes do `decided_at` (`14:12:54Z`). Conteúdo bate com os 3 índices parciais descritos no comentário da #59. |

**Conclusão honesta desta seção:** a #66 corrigiu a causa raiz que ela mesma documentou (vazamento de variáveis de sessão IDE), mas **não eliminou o vazamento por completo** — 3 das 10 issues desta janela (#59, #69, #70) tiveram edições reais vazando para a working tree do operador, uma delas (#69) parcialmente autodetectada pelo próprio modelo mas sem limpeza completa. Nenhuma dessas 3 chegou a ser commitada (ficaram como `M` sem commit, confirmado via `git status` na raiz do repo), então não há risco de a contaminação ter ido para o histórico do Git — mas o objetivo original da #66 ("Read/Edit resolvem contra o clone isolado, não a working tree real") não se sustentou hoje para 3 de 10 casos. **Consequência direta e mais grave**: como a métrica `diff_lines` usada pelo gate de risco é calculada contra o clone isolado (`repo_dir`), e o diff real ficou no lugar errado, essas 3 issues foram classificadas como `no_action_needed` (`diff_lines: 0`) mesmo tendo um fix real e não-trivial pronto em disco — ver seção 11 para a análise completa desse efeito colateral.

---

## 2. Resumo de issues da janela

| Categoria | Quantidade | Issues |
|---|---|---|
| Criadas pelo agent-preditivo — bug (`latencia_alta`) | 4 | #69, #70, #71, #72 |
| Criadas pelo agent-preditivo — oportunidade/história de negócio | 1 | #68 |
| Backlog anterior reprocessado (label `backlog-anterior`) | 5 | #55, #59, #60, #61, #62 |
| **Total processado nesta janela** | **10** | |
| Corrigidas com merge automático (score < threshold) | **0** | — nenhuma decisão `autonomo` ocorreu hoje |
| Geraram PR para revisão manual (`needs-human-review`) | 2 | #62 (PR #67), #71 (PR #73) — ambas mergeadas manualmente |
| `no_action_needed` (sem diff **no clone isolado**, ver seção 11 sobre 3 desses casos terem diff real vazado) | 7 | #55, #59, #60, #68, #69, #70, #72 |
| Escalaram para `agent-stuck` | 1 (evento novo hoje) | #61 |

---

## 3. Tabela de decisões do agente

Fonte: `agent_ops.risk_decisions` (Postgres) + `agent_ops.flagged_signals` (para `first_seen_at`) + GitHub (para #62, cujo `risk_decision` se perdeu — ver nota).

| Issue | Tipo de sinal | Score / threshold | Decisão | Motivo (resumo) | Detecção → decisão |
|---|---|---|---|---|---|
| #60 | `latencia_alta` account-service (backlog) | 35.00 / 40.00 (alto) | `no_action_needed` | Duas causas conhecidas (#34/#36) já corrigidas; nenhuma nova achada | n/a (backlog, decidida às 13:22:22, 3min *antes* do início oficial da janela — daemon já processando ao subir) |
| #72 | `latencia_alta` transaction-service | 42.00 / 20.00 (crítico) | `no_action_needed` | Duas causas conhecidas (#37/#38) já corrigidas; nenhuma nova achada por leitura estática | 13:26:49.52 → 13:32:01.37 = **5m12s** |
| #71 | `latencia_alta` pix-key-service | 42.59 / 20.00 (crítico) | `humano` → PR #73, mergeado | Query sem filtro `deleted_at` não usava índice parcial; fix real (17 linhas), cobertura 0% | 13:26:46.61 → decisão 13:40:18.68 (**13m32s**) → merge humano 14:31:39 (**1h04m53s**) |
| #70 | `latencia_alta` account-service | 35.00 / 40.00 (alto) | `no_action_needed` (mas com diff real vazado p/ working tree — ver seção 1/11) | `defer(Account.cpf)` proposto; ficou sem commit na tree errada | 13:26:43.60 → 13:48:39.02 = **21m55s** |
| #69 | `latencia_alta` onboarding-service | 35.00 / 40.00 (alto) | `no_action_needed` (idem — diff real, vazado parcialmente) | Batching de `publish_events` (2 flushes Kafka → 1); ficou sem commit | 13:26:40.29 → 13:59:33.03 = **32m53s** |
| #68 | oportunidade `onboarding_get_inexistente` (duplicata da #63) | 78.00 / 20.00 (crítico) | `no_action_needed` (`humano` teria sido o veredito se houvesse diff — mas SDK concluiu sem gerar diff) | Confirmou que não há gap real; contrato citado na issue (`api-conventions.md` §"Códigos de erro") não existe no arquivo | 13:21:35.39 → 14:05:51.08 = **44m16s** |
| #59 | `latencia_alta` onboarding-service (backlog) | 35.00 / 40.00 (alto) | `no_action_needed` (diff real vazado — ver seção 1/11) | 3 índices parciais propostos para queries de risco (`check_documento_reciclado`/`check_padrao_mula`); ficou sem commit | n/a (backlog) → decidida 14:12:54 |
| #55 | Endpoints internos sem proteção real (backlog) | 35.00 / 40.00 (alto) | `no_action_needed` | Escopo era "avaliar e decidir", não implementar — sem código a mudar nesta iteração | n/a (backlog) → decidida 14:20:16 |
| #62 | `latencia_alta` transaction-service (backlog) | **42.48** / 20.00 (crítico, via comentário do PR — linha perdida em `risk_decisions`, ver nota) | `humano` → PR #67, mergeado | Índice não-parcial em `valor` para lookup usado por `transaction-service`; fix real (17 linhas), cobertura 0% | PR aberto 12:48:52 (antes do início oficial da janela) → merge humano 14:31:20 |
| #61 | `latencia_alta` pix-key-service (backlog) | — (não chegou a calcular score na 2ª/3ª tentativa) | `agent-stuck` (escalação nova, hoje) | 1ª falha: erro real novo do SQLAlchemy (`subject table for an INSERT... got None`); 2ª/3ª: colisão mecânica de branch órfã deixada pela 1ª falha (ver seção 10) | 1ª tentativa 13:05:09 → escalado 13:15:28 = **10m19s** |

**Nota sobre #62:** o container do Postgres (`agent_ops`) foi recriado às `13:16:56Z`, mas o PR #67 foi criado às `12:48:52Z` — antes de o Postgres novo existir. O daemon `agent-local` (rodando continuamente, independente do script da janela) processou #62 contra o Postgres da sessão anterior, que foi substituído minutos depois; o `risk_decision` correspondente não sobreviveu à troca de ambiente. O score (42.48) e a decisão (`humano`) vêm do comentário do gate no próprio PR #67, não do banco.

---

## 4. Issues abertas ao final da janela

| Issue | Estado | Labels | Assignee | Observação |
|---|---|---|---|---|
| **#61** | OPEN | `bug`, `agent-stuck`, `backlog-anterior` | jcorreaviana | Escalação nova de hoje — root cause real (erro SQLAlchemy) ainda não investigada; ver seção 10/13 |
| **#63** | OPEN | `business-story`, `backlog-anterior` | — (sem assignee) | **Nunca foi reprocessada nesta janela** — 0 comentários novos, nenhuma linha em `risk_decisions`/`flagged_signals` para #63. Candidata válida (`is:open no:assignee label:business-story,bug`) o tempo todo, mas o agent-preditivo criou uma **duplicata** (#68) para o mesmo cenário em vez de o agent-local pegar a #63 original — ver seção 7/13 |

Todas as outras 8 issues tocadas nesta janela (#55, #59, #60, #62, #68, #69, #70, #71, #72) terminaram **CLOSED**.

---

## 5. Issues fechadas automaticamente pelo agente (sem intervenção humana)

7 issues, todas via `_handle_no_action_needed` (comentário explicativo + `close_issue`, `agent_local/polling.py`) — nenhuma teve merge de código associado:

- **#55** — escopo era avaliação, não implementação; nada a fechar por código.
- **#59** — 3 índices parciais propostos, mas diff ficou (sem commit) na tree externa por vazamento de isolamento; issue fechada como se fosse no-op genuíno.
- **#60** — duas causas conhecidas já corrigidas; nenhuma nova achada.
- **#68** — confirmou ausência de gap real (duplicata da #63); contrato citado na issue não existe no arquivo referenciado.
- **#69** — batching de Kafka proposto, mesmo problema de vazamento parcial da #59.
- **#70** — `defer(Account.cpf)` proposto, mesmo problema de vazamento da #59.
- **#72** — duas causas conhecidas já corrigidas; nenhuma nova achada.

**Ressalva importante, repetida da seção 1**: 3 destes 7 (#59, #69, #70) tinham um diff real e não-trivial pronto — a classificação `no_action_needed` é tecnicamente incorreta para eles, causada pelo vazamento de isolamento distorcendo o cálculo de `diff_lines`. Do ponto de vista de "decisão autônoma correta", só 4 das 7 (#55, #60, #68, #72) são `no_action_needed` genuínos.

---

## 6. Issues que geraram PR para revisão manual

| Issue | PR | Score / threshold | Motivo do gate | Cobertura de teste | Status |
|---|---|---|---|---|---|
| #62 | [#67](https://github.com/jcorreaviana/bank-of-decoy/pull/67) | 42.48 / 20 (tier **crítico**) | Score acima do threshold do tier crítico — mesmo um diff pequeno (17 linhas) dispara revisão humana neste tier | **0%** — nenhum teste novo cobrindo o índice adicionado | **Aprovado e mergeado** manualmente por jcorreaviana às 14:31:20Z |
| #71 | [#73](https://github.com/jcorreaviana/bank-of-decoy/pull/73) | 42.59 / 20 (tier **crítico**) | Idem — `pix-key-service` é tier crítico, threshold baixo (20) por criticidade do serviço, não pelo tamanho do diff | **0%** — idem | **Aprovado e mergeado** manualmente por jcorreaviana às 14:31:39Z |

Os dois merges aconteceram com **19 segundos de diferença** — consistente com terem sido revisados/mergeados em lote pelo operador, provavelmente no momento em que a fase de espera do `validation_window.py` (`wait_for_agents_idle`) estava bloqueada esperando exatamente essas duas issues saírem do estado "atribuída, sem decisão terminal".

Nenhuma das duas teve teste automatizado cobrindo a mudança (`Cobertura de teste: 0%` no comentário do gate) — isso por si só quase garante cair no threshold humano em qualquer tier, já que cobertura zero é um dos sinais que empurram o score para cima em `risk_score.py`.

---

## 7. Recorrência — a correção resolveu de verdade?

**Resposta curta: não dá para saber ainda, e a razão é operacional, não do código.**

Os 4 containers de domínio foram criados às `13:16:56Z` — **antes** de qualquer merge desta janela (`14:31:20Z` e `14:31:39Z`). Como a janela rodou com `--skip-up` (a seu pedido, ambiente já estava no ar) e não houve rebuild de imagem depois dos merges, **os containers em execução durante toda a janela nunca continham o código corrigido de #62/#71** — nem depois do merge. Qualquer leitura de "o sinal sumiu depois do fix" seria enganosa: o sinal não reapareceu simplesmente porque, sem chaos ativo (ver aviso crítico no topo) e com tráfego sintético em ritmo constante, não havia razão para o p95 voltar a subir de qualquer forma, corrigido ou não.

Teste real de recorrência (comparando p95 antes e depois de `14:31Z` via Prometheus, serviços `transaction-service` e `pix-key-service`): **latência p95 permaneceu estatisticamente idêntica antes e depois do merge** (~0.065–0.075s em ambos os serviços, nas duas janelas de 30min antes/depois de 14:31Z) — o que é exatamente o esperado quando o binário em execução não mudou, não evidência de que o fix funcionou ou falhou.

**Para um teste real de recorrência**: seria necessário `docker compose -f docker-compose.test.yml up -d --build account-service pix-key-service` (rebuild só desses dois serviços, já mergeados em `main`) e então re-rodar tráfego sintético observando se o p95 muda. Não fiz isso porque você pediu para não mexer no ambiente até sua instrução.

Nenhuma issue nova de `latencia_alta` para `pix-key-service`/`transaction-service` foi criada depois dos merges (`14:31Z` até o fim da janela, `15:29Z`) — mas com só ~54 minutos de tráfego pós-merge e sem chaos ativo, a ausência de novo sinal não é evidência forte de nada.

---

## 8. Correlação antes/depois (golden signals via Prometheus)

Consultas diretas a `http_request_duration_seconds_bucket` (mesma query de `agent_preditivo/prometheus_client.py`, `histogram_quantile(0.95, ...)`), granularidade de 15s entre `13:20:00Z` e `13:35:00Z` (a transição real), e 2min entre `13:15Z` e `15:30Z` (janela completa):

**Caso 1 — onboarding-service:**
```
13:20:00 → 13:25:45   p95 = 0.00475s  (baseline, sem tráfego real ainda)
13:26:15              p95 = 0.0695s   (salto abrupto assim que o tráfego sintético começa)
13:26:30              p95 = 0.0737s   (pico observado nesta janela)
13:27:00 em diante     p95 estabiliza em ~0.065–0.070s por 2h inteiras, sem variação
```

**Caso 2 — transaction-service:**
```
13:20:00 → 13:26:15   p95 = 0.00475s
13:26:30              p95 = 0.0611s
13:30:15              p95 = 0.0819s   (pico observado nesta janela, o mais alto dos 4 serviços)
13:30:45 em diante     estabiliza em ~0.072–0.073s pelo resto da janela
```

**Caso 3 — account-service** (o único dos 4 com salto proporcionalmente pequeno):
```
13:20:00 → 13:26:15   p95 = 0.00475s
13:31:15              p95 = 0.00948s  (pico — só ~2x o baseline, não ~15x como os outros 3)
resto da janela        estabiliza em ~0.0090–0.0093s
```

**Leitura honesta:** em nenhum dos 3 casos o p95 real medido chega perto dos valores citados nos corpos das issues (`#69`: 0.356s: `#70`: 1.959s; `#71`: 1.240s; `#72`: 2.877s). O maior pico real observado em qualquer serviço, em qualquer instante da janela, foi **0.082s** (transaction-service, 13:30:15) — **35x menor** que o valor mais alto citado (2.877s, #72). Isso é consistente com o mecanismo de detecção do `agent-preditivo` ter capturado um valor instável de `histogram_quantile` bem no instante de transição de zero tráfego para tráfego real (poucas amostras no bucket, quantil interpolado de forma numericamente instável) — não com uma medição sustentada. Depois de ~1 minuto de tráfego real, o p95 se estabiliza e fica **absolutamente flat** pelas 2 horas seguintes em todos os 4 serviços — sem chaos ativo (ver aviso no topo), não há razão para esperar variação, e não houve.

Isso reforça a suspeita, já registrada no próprio código do projeto (`docs/licoes-aprendidas-operacao-real.md`), de que `latencia_alta` no `agent-preditivo` tem uma classe de falso positivo ligada à baseline "mediana histórica" ser calculada com poucas amostras logo após o ambiente subir — e é o padrão dominante desta janela específica (4 de 4 sinais de `latencia_alta` desta janela caem nele, considerando a ausência confirmada de chaos).

---

## 9. MTTR (tempo entre sinal e decisão final)

Calculado como `decided_at` (ou `first_seen_at` do PR para os casos com revisão humana) menos `first_seen_at` em `flagged_signals`, só para os 5 sinais **detectados nesta janela** (#68–#72) — os 5 itens de backlog não têm `first_seen_at` comparável (foram criados no dia anterior, sob um regime de bloqueio manual que não reflete tempo de processamento real do agente).

| Tipo | MTTR até decisão do agente (n) | Observação |
|---|---|---|
| `latencia_alta` (agregado, #69/#70/#71/#72) | **18m23s** (n=4) | Varia de 5m12s (#72, no-op mais simples) a 32m53s (#69, envolveu tentativa de fix + vazamento de isolamento) |
| Oportunidade/negócio (#68) | 44m16s (n=1) | Investigação mais longa — envolveu ler 2 specs de negócio + validar referência de contrato inexistente |
| **Agregado geral (todos os 5 sinais novos)** | **23m34s** | |
| #71 — MTTR até merge humano (não só decisão do agente) | 1h04m53s | +51m21s além da decisão do agente, tempo de espera por revisão humana |

Não é possível calcular MTTR "clássico" (sinal → resolução real em produção) para nenhum dos 7 casos `no_action_needed`, porque "resolução" nesses casos é uma conclusão de análise, não uma mudança que chega a rodar — e para #59/#69/#70 nem chegou a ser commitada.

---

## 10. Taxa de falso positivo em `agent-stuck`

**Comparação honesta entre ontem (pré-fix #65) e hoje (pós-fix):**

| Janela | Escalações | Falha real vs. mecânica |
|---|---|---|
| Sessão de ontem (antes da #65), #60/#61/#62 | 3 escalações, **9 eventos de falha no total** (3 tentativas × 3 issues) | **9/9 (100%) mecânicas** — todas o mesmo erro `git checkout -b ... already exists`, causado por branch órfã deixada por um ciclo anterior de `no_action_needed` que nunca fechava a issue |
| Hoje (depois da #65), #61 | 1 escalação, 3 eventos de falha | **1/3 genuína** (erro novo do SQLAlchemy, `subject table for an INSERT, UPDATE or DELETE expected, got None` — nunca visto antes, causa raiz não investigada) + **2/3 mecânicas** (colisão de branch, mesma classe do bug da #65) |

**O que isso mostra, com honestidade:** a correção da #65 eliminou a classe de falha mecânica **no caminho que ela cobriu** (`_handle_no_action_needed`) — nenhuma das 7 conclusões `no_action_needed` de hoje deixou uma branch órfã (confirmado: `git branch` no clone isolado não lista branches para #55/#59/#60/#68/#69/#70/#72). Mas **o caminho de falha genérica** (`_handle_process_issue_failure`, "destino 3" do ciclo de vida) **nunca ganhou a mesma limpeza** — li o código (`agent_local/polling.py`, linhas ~120–150) e confirmei que essa função não chama `delete_local_branch` em nenhum branch de execução, ao contrário de `_handle_no_action_needed`. Resultado: quando *qualquer* falha acontece depois que `create_issue_branch` já rodou com sucesso — não só o caso "no-op sem fechar issue" que a #65 mirou — a branch fica órfã e uma nova tentativa da mesma issue colide, reproduzindo o sintoma da #65 por uma porta lateral que ela não fechou. Foi exatamente isso que aconteceu com #61 hoje: a 1ª falha (genuína, SQLAlchemy) criou a branch e falhou depois; as tentativas 2 e 3 nunca tiveram chance de rodar de verdade, porque colidiram na própria branch órfã da tentativa 1.

**Recomendação concreta**: estender `_handle_process_issue_failure` para também chamar `git_ops.delete_local_branch` (melhor-esforço, mesmo padrão da #65) sempre que a branch já tiver sido criada antes da falha — isso é um candidato natural de issue de acompanhamento.

---

## 11. Estudo de caso — falhas encontradas e corrigidas durante o processo

### 11.1 — Issue #65: `no_action_needed` não fechava a issue nem limpava a branch

- **Causa raiz**: `_handle_no_action_needed` registrava a decisão, comentava e desatribuía — mas nunca fechava a issue nem apagava a branch local criada para aquele ciclo. Como a issue continuava aberta e sem assignee, `list_candidate_issues()` a reoferecia, uma nova seleção recriava o mesmo nome de branch (`agent-local/issue-N`) e colidia com `git checkout -b`, escalando para `agent-stuck` depois de 3 tentativas idênticas — sem nenhuma falha real de processamento em nenhuma delas.
- **Descoberta**: ao vivo, durante a janela de validação da #54 (ontem), observado primeiro em #62, depois confirmado em #60 e #61 com o mesmo padrão exato.
- **Correção** (commit `3aab6e6`): `_handle_no_action_needed` passou a chamar `github_client.close_issue` (mesma semântica terminal do caminho com diff, `Closes #N`) e `git_ops.delete_local_branch` (melhor-esforço). Testes de regressão novos em `agent-local/tests/unit/test_git_ops.py`, reproduzindo o cenário exato de reseleção pós-no-op. Validado manualmente contra uma issue real (#64, removida após validação).
- **Auditoria retroativa feita nesta sessão**: os dois itens do critério de aceite (fechar a issue; limpar a branch) foram confirmados implementados e testados. Gap encontrado: a correção nunca tinha sido registrada no changelog (`docs/escopo-arquitetura.md`) apesar de ser cronologicamente anterior à v47/v48 — corrigido com a entrada retroativa v49 nesta sessão.
- **Achado novo desta janela** (seção 10): a correção não cobre o caminho de falha genérica (`_handle_process_issue_failure`), que pode deixar a mesma classe de branch órfã por um motivo diferente — confirmado ao vivo em #61 hoje.

### 11.2 — Issue #66: vazamento de isolamento entre o subprocess do SDK e a working tree real

- **Causa raiz**: o transporte do Claude Agent SDK filtra só `CLAUDECODE` do ambiente herdado antes de repassar tudo ao subprocess do CLI empacotado (`claude_agent_sdk/_bundled/claude.exe`). Variáveis que identificam uma sessão IDE anexada (`CLAUDE_CODE_MESSAGING_SOCKET`/`TOKEN`/`SESSION_ID`) passavam direto; o CLI usa esse canal para se conectar à sessão IDE ativa, resolvendo `Read`/`Edit` contra a workspace real aberta no VS Code em vez do `cwd` explícito (`ClaudeAgentOptions(cwd=cwd)`, que chega corretamente ao subprocess mas é ignorado nesse cenário).
- **Gatilho**: daemon do `agent-local` lançado como subtarefa em background de uma sessão interativa do Claude Code no VS Code — herda o socket/token de quem o lançou.
- **Correção** (commit `097cb67`): lista positiva de variáveis repassadas ao subprocess (`_minimal_subprocess_env`, `_ALLOWED_ENV_PASSTHROUGH`), reduzindo o `os.environ` do processo chamador antes da chamada ao SDK (não uma blacklist, que reabriria o buraco a cada variável nova). Teste de regressão real (não mockado) em `tests/integration/test_isolation_leak.py`.
- **Achado novo desta janela, importante para o registro histórico**: mesmo com os daemons rodando hoje em terminais limpos, fora de qualquer sessão Claude Code/VS Code (a mitigação recomendada pelo próprio README após a #66), **3 de 10 issues (#59, #69, #70) ainda tiveram edições vazando para a working tree real** — não pelo mesmo mecanismo de socket IDE (não há sessão IDE anexada desta vez), mas por o próprio modelo, dentro da sessão do SDK, editar o caminho absoluto errado por conta própria. A #69 é o caso mais informativo: o modelo se autocorrigiu via `git rev-parse --show-toplevel`, mas não reverteu a tentativa errada, deixando os dois lados contaminados. Isso sugere que a correção da #66 resolveu a causa que investigou (vazamento de variável de ambiente), mas o problema mais amplo — "o modelo, com acesso de `Edit` a caminhos absolutos, pode editar fora do `cwd` pretendido, e nada no `can_use_tool` (`agent_local/sdk_invocation.py::_deny_out_of_scope_tools`) restringe `Edit` a um prefixo de caminho" — continua aberto. `_deny_out_of_scope_tools` permite `Edit` incondicionalmente (linha 164-165), sem checar se o caminho do arquivo está dentro de `cwd`. Candidato natural de próxima issue.

---

## 12. Uso de recursos

Dado real disponível, com limitação clara:

- **Tráfego sintético**: 956 contas prontas em 2h (`synthetic_traffic.log`, evento `fim`), transações reais criadas continuamente, 106 respostas HTTP 404 e 86 respostas 422 registradas no log do gerador (esperado — parte do cenário sintético testa caminhos de erro, não indicativo de falha).
- **Ciclos de chaos**: 40 tentativas em 2h (a cada 3 minutos, `--cycle-gap-minutes` default), **100% falharam** antes de fazer qualquer chamada HTTP (ver aviso crítico no topo) — então não há dado de "chamadas ao endpoint de chaos" para reportar.
- **Custo/tempo de SDK por ciclo**: **não disponível para esta janela**. `SDKInvocationResult.total_cost_usd` é computado pelo wrapper (`agent_local/sdk_invocation.py`) e devolvido em `process_issue`, mas só chega a log via `logger.info`/stdout — e, como registrado na seção 1, o stdout dos daemons de hoje não foi capturado em arquivo. Não tenho como reconstruir esse número retroativamente; se for importante para o artigo, recomendo adicionar `total_cost_usd` como coluna em `risk_decisions` (hoje só grava `risk_score`/`decision`/`pr_number`) para não depender de captura de log no futuro.
- **Nenhuma métrica de tokens** está exposta em nenhuma camada do projeto (`agent_ops_db`, `daemon.log`, ou o SDK) além do `total_cost_usd` agregado por chamada — não há breakdown de tokens de entrada/saída.

---

## 13. Outras observações relevantes

1. **Contradição na permissão de commit do SDK**: `agent_local/sdk_invocation.py` define `ALLOWED_TOOLS` incluindo `"Bash(git add *)"`/`"Bash(git commit *)"`, e `_deny_out_of_scope_tools` de fato permite esses padrões — o design pretendido é o modelo commitar localmente (só não pode `git push`/`gh`). Mas o prompt gerado por `build_task_prompt` diz, na mesma frase, "seu acesso está restrito a Read/Edit" e depois "faça commit local (git add + git commit)" — mensagem internamente inconsistente. E, na prática, **6 dos 10 comentários de issue desta janela e da sessão anterior relatam Bash/PowerShell sendo negados com a mensagem literal "Permission... denied... don't ask mode"** (não a mensagem de `_deny_out_of_scope_tools`, que tem texto diferente) — isso é a mesma classe de bloqueio de classificador de "auto mode" do harness do Claude Code que a própria sessão que gerou este relatório encontrou ao tentar `git branch -D` no clone isolado (seção sobre #63, conversa anterior). Ou seja: há uma camada de permissão adicional, fora de `can_use_tool`, bloqueando consistentemente o commit local que o design pretendia permitir — vale investigar isso como issue própria, porque hoje o resultado prático é que **nenhuma issue com fix real passou pelo caminho "modelo commita, wrapper empurra e abre PR" sem alguém ter que commitar manualmente ou (nos casos #59/#69/#70) perder o fix na classificação `no_action_needed`**.
2. **Duplicidade de specs/issues do agent-preditivo**: `specs/business/25-onboarding-get-inexistente.md` e `26-onboarding-get-inexistente.md` são quase idênticas (confirmado por leitura), geradas a partir do mesmo cenário (`tests/scenarios/onboarding_get_inexistente.md`) em execuções diferentes do agente de oportunidades — e a issue #68 de hoje é uma duplicata funcional da #63 (aberta ontem, mesmo veredito "sem gap real" nas duas). O agente de detecção de oportunidades não verifica se já existe uma issue aberta para o mesmo cenário antes de criar uma nova. Recomendo fechar #63 como duplicata da #68 (ou vice-versa) e registrar essa lacuna de deduplicação como issue de acompanhamento.
3. **`tests/scenarios/onboarding_get_inexistente.md` seguiu modificado durante toda a sessão** (aparece no `git status` desde o início desta conversa) — não investiguei o conteúdo desse diff especificamente; vale conferir se é trabalho seu em andamento antes de descartar.
4. **O comando de migrations que passei antecipadamente funcionou sem problema** — as 5 migrations foram aplicadas manualmente com sucesso (confirmado indiretamente: os fixes que dependiam de schema, como os índices de #59/#71, referenciam índices/migrations existentes sem erro relatado de schema desatualizado).
5. Os arquivos `agent-local/daemon.log`/`agent-preditivo/daemon.log` deveriam, para a próxima janela, ser redirecionados explicitamente pelo operador (`... > agent-local\daemon.log 2>&1` ou equivalente) para preservar rastreabilidade linha-a-linha — hoje a única fonte de verdade granular foi o banco `agent_ops` e o GitHub, que cobrem decisões mas não todo o raciocínio intermediário do SDK.

---

## Por que um documento só, não dois

Optei por um único arquivo em vez de separar "artigo técnico" e "documentação do repositório": o público de ambos se sobrepõe quase totalmente (quem lê um provavelmente quer o outro), e manter dois documentos sobre o mesmo evento com evidência idêntica convida a divergência silenciosa entre eles com o tempo (um é atualizado, o outro não). A estrutura acima já serve aos dois modos de leitura — o aviso crítico + seções 1, 10 e 11 têm a narrativa que um artigo técnico quer (descoberta, causa raiz, correção, o que ainda falta), e as tabelas das seções 2–9 servem como referência rápida de documentação. Se depois for necessário adaptar para publicação externa (artigo de blog, por exemplo), esse arquivo é uma base completa da qual cortar, não uma fonte a reconciliar com outra.
