# Lições aprendidas — operação real dos agentes

Registro vivo de achados sobre o comportamento do sistema de agentes (agent-preditivo, agent-local) observados em operação real — não simulada — contra o ambiente efêmero, com tráfego sintético contínuo (`scripts/synthetic_traffic.py`). Complementa `docs/escopo-arquitetura.md` (fonte de verdade de decisões de arquitetura): aqui entram achados de comportamento/execução real, não decisões de desenho. Formato livre, atualizado conforme surgem novos cenários — sem compromisso de estrutura final por enquanto.

Primeira janela de validação: 2026-08-28, ~2h de tráfego sintético contínuo contra `docker-compose.test.yml`, com os dois daemons rodando organicamente (sem intervenção manual em qual issue processar).

## Bugs reais encontrados e corrigidos durante a janela

- **`agent-local/agent_local/test_runner.py`: `venv_python` desatualizado após criar o venv.** Quando o serviço afetado não tem `.venv` no clone (sempre o caso — venvs não vão pro git), o código cria um venv novo mas continuava usando o caminho calculado *antes* da criação (`.venv/bin/python`, convenção Linux) para instalar dependências e rodar o pytest, em vez de recalcular para `.venv/Scripts/python.exe` no Windows. Resultado: `FileNotFoundError: [WinError 2]`, ciclo abortado depois do SDK já ter commitado uma correção real (issues #37 e #38 — commits válidos ficaram presos localmente no clone, nunca chegaram a virar PR). Corrigido recalculando `venv_python` logo após a criação. Validado: issue #36, processada depois do fix, completou o ciclo inteiro (SDK → teste real com 62% de cobertura → score 26.91 → merge automático real, PR #39).

## Achados de configuração/infraestrutura (corrigidos no setup, antes de liberar tráfego)

- Migrations nunca tinham sido aplicadas no ambiente efêmero recém-criado — nem as 4 de domínio, nem as de `agent_ops` (`flagged_signals`/`risk_decisions`). O `docker-compose.test.yml` só cria os bancos vazios (`infra/postgres/init-databases.sh`); o schema em si depende de `alembic upgrade head` rodado manualmente por fora, e isso não estava documentado em nenhum lugar do fluxo de subida do ambiente.
- `agent-local/.env.example`: `TEST_DATABASE_PORT=5433` não corresponde a nada — nenhum compose expõe essa porta. A convenção real (confirmada em `specs/tech/testing.md` e nos `.env.example` dos serviços de domínio) é a porta 5432 do próprio ambiente efêmero.
- `scripts/requirements.txt` não listava `httpx`, usado pelo `synthetic_traffic.py`.
- stdout dos dois daemons vem bufferizado quando redirecionado para arquivo (não é TTY) — logs ficavam invisíveis até o processo morrer. Precisa `python -u` / `PYTHONUNBUFFERED=1` para operação com log em tempo real.

## Gaps de design encontrados — ainda não corrigidos, pendentes de decisão

- **Resultado do `pytest` (passou/falhou) não influencia o gate.** `test_runner.run_tests_for_service` calcula `TestRunResult.passed` (via `returncode`), mas `process_issue` (`polling.py`) só lê `.coverage_fraction` — `.passed` é descartado, nunca chega em `calculate_risk_score` nem em nenhum log. Hoje, uma suíte **falhando** não impede merge automático, se cobertura e diff derem um score baixo. Não causou dano na janela (conferido: a suíte do `account-service` pós-merge da #36 passa de verdade, 10 passed/22 skipped), mas o mecanismo não teria percebido se tivesse falhado.
- **PR aberto incondicionalmente mesmo sem diff.** Quando o SDK avalia a issue e decide, corretamente, não fazer nenhuma mudança (`diff_lines: 0` — comportamento esperado por instrução do próprio prompt, "se a issue tiver premissa incorreta... pare e explique, sem fazer commit"), o wrapper tenta `git push` + `gh pr create` do mesmo jeito. Sem commits entre a branch e a `main`, o `gh pr create` falha, a issue fica sem explicação nenhuma do que aconteceu. Reproduzido 2x na janela (issues #34 e #35).
- **Nenhuma trilha de recuperação quando o processamento falha após `assign_self`.** `github_client.assign_self` roda bem no início de `process_issue`; qualquer falha depois disso (os dois casos acima, ou qualquer exceção) só gera log + notificação Discord — sem desatribuir, comentar ou fechar a issue. Como `pick_candidate_issue` só considera issues sem assignee, a issue fica presa: atribuída, sem PR, sem comentário, fora da fila do agent-local para sempre. Afetou #34, #35, #37, #38 nesta janela — só #36 completou o ciclo inteiro.

## Comportamentos validados como corretos

- Dedup de sinais via `flagged_signals` funcionando: o gap de #35 (`pix_key_conta_inexistente`) foi reavaliado em ciclos seguintes do agent-preditivo e corretamente reconhecido como "já sinalizado", sem reabrir issue duplicada.
- Ciclo completo ponta a ponta validado com dados reais: sinal detectado (Prometheus) → issue criada (Discord notificado) → agent-local pegou, corrigiu, testou, calculou score → PR aberto → merge automático real (#36 → PR #39), tudo sem intervenção manual.

## Observações / possíveis melhorias futuras (não urgentes)

- `latencia_alta` do agent-preditivo teve alta taxa de falso positivo na partida a frio do ambiente (comparando p95 atual contra mediana histórica calculada com poucas amostras) — gerou issues para os 4 serviços quase simultaneamente, sendo que só uma (#36) tinha uma correção real e útil por trás. Possível melhoria: exigir um número mínimo de amostras históricas antes de habilitar essa comparação.
- `specs/tech/testing.md` menciona suíte rodando "no pipeline de CI a cada push", mas não existe workflow de CI configurado (`.github/workflows` ausente). Não é um achado novo desta janela, só uma confirmação de que ainda é aspiracional.
