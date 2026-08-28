#!/bin/bash
# Prova de ponta a ponta REAL (nao mockada) de que o pipeline de agentes
# reconhece sinais de caos (specs/business/21-filtro-caos-pipeline-agentes.md):
#
#   1. liga CHAOS_ENABLED=true de verdade num servico
#   2. gera trafego real ate violar o threshold de taxa de erro
#   3. roda a deteccao real do agent-preditivo (bug_detection.py, sem mock)
#      e o registro real (registration_agent.py) - cria uma issue real no
#      GitHub, com label `chaos-test` e aviso no corpo
#   4. roda a selecao real do agent-local (polling.pick_candidate_issue,
#      sem mock) e confirma que ela pula a issue de caos
#   5. desliga o caos, fecha a issue de teste, resolve a linha em
#      agent_ops.flagged_signals (nao ha funcao de "resolve" no codigo -
#      feito via SQL direto, documentado aqui)
#
# Fronteira de seguranca deliberada: este script NUNCA chama
# agent_local.polling.process_issue()/invoke_sdk() em nenhuma issue real -
# nem na de caos (e o que estamos provando que NAO acontece) nem em
# qualquer outro candidato real que exista no repositorio no momento
# (ex. a issue #14 do backlog real, que list_candidate_issues() tambem
# retorna). Rodar o agente local "de verdade" ate o fim tentaria
# implementar essa outra issue de verdade (clone, branch, Claude Code SDK,
# possivel merge automatico) - fora do escopo desta validacao, e uma acao
# grande demais para disparar como efeito colateral de um script de teste.
#
# Requer, no ar: ambiente principal (docker-compose.yml), gh autenticado,
# Ollama com o modelo configurado (PREDICTIVE_AGENT_MODEL, default
# llama3.2:3b) - o agente de registro usa chat() para escrever a narrativa
# da issue.
#
# Uso: bash scripts/validate_chaos_pipeline_e2e.sh [servico]
# servico default: account-service (ver SERVICE_CRITICALITY em
# agent-preditivo/agent_preditivo/registration_agent.py para as opcoes).
#
# Efeitos colaterais reais que este script produz e desfaz sozinho:
# - cria e fecha uma issue real no GitHub (label bug + chaos-test)
# - grava e resolve uma linha em agent_ops.flagged_signals
# - liga e desliga CHAOS_ENABLED no servico escolhido (force-recreate do
#   container, mesmo mecanismo do README.md secao "Camada de caos")

set -euo pipefail
cd "$(dirname "$0")/.."

SERVICE="${1:-account-service}"
case "$SERVICE" in
  onboarding-service) PREFIX="ONBOARDING"; PORT=8001; PATH_="/v1/onboarding"; METHOD=POST ;;
  account-service) PREFIX="ACCOUNT"; PORT=8002; PATH_="/v1/accounts"; METHOD=POST ;;
  pix-key-service) PREFIX="PIX_KEY"; PORT=8003; PATH_="/v1/pix-keys"; METHOD=POST ;;
  transaction-service) PREFIX="TRANSACTION"; PORT=8004; PATH_="/v1/transactions"; METHOD=POST ;;
  *) echo "Servico desconhecido: $SERVICE"; exit 1 ;;
esac

echo "== [1/6] Ligando caos de verdade em $SERVICE (rate=0.9, tipo=503) =="
export "${PREFIX}_CHAOS_ENABLED=true"
export "${PREFIX}_CHAOS_FAILURE_RATE=0.9"
export "${PREFIX}_CHAOS_FAILURE_TYPES=503"
docker compose up -d --force-recreate "$SERVICE"
sleep 3

echo "== [2/6] Gerando trafego ate violar taxa_erro > 5% em 5 min =="
for i in $(seq 1 30); do
  curl -s -o /dev/null -X "$METHOD" "http://localhost:${PORT}${PATH_}" -H "Content-Type: application/json" -d '{}'
done
echo "aguardando o Prometheus fazer scrape (2 ciclos de 15s)..."
sleep 32

echo "== [3/6] Deteccao + registro REAIS do agent-preditivo (sem mock) =="
cd agent-preditivo
ISSUE_NUMBER=$(./.venv/Scripts/python.exe -c "
from agent_preditivo.bug_detection import detect_bugs_for_service
from agent_preditivo.registration_agent import register_bug

signals = detect_bugs_for_service('$SERVICE')
erro_alto = next((s for s in signals if s.signal_type == 'erro_alto'), None)
if erro_alto is None:
    raise SystemExit('taxa de erro nao violou o threshold - trafego insuficiente ou Prometheus nao fez scrape a tempo')
assert erro_alto.chaos_ativo is True, 'chaos_ativo deveria ser True com o caos ligado'

issue_number = register_bug(erro_alto)
if issue_number is None:
    raise SystemExit('register_bug retornou None - ja existe sinal em aberto (agent_ops.flagged_signals), resolva antes de rodar de novo')
print(issue_number)
")
cd ..
echo "Issue real criada: #$ISSUE_NUMBER"
gh issue view "$ISSUE_NUMBER" --json labels,assignees

echo "== [4/6] Desligando o caos (nao precisa mais dele para o resto do teste) =="
unset "${PREFIX}_CHAOS_ENABLED" "${PREFIX}_CHAOS_FAILURE_RATE" "${PREFIX}_CHAOS_FAILURE_TYPES"
docker compose up -d --force-recreate "$SERVICE"

echo "== [5/6] Selecao REAL do agent-local (pick_candidate_issue, sem mock) =="
cd agent-local
./.venv/Scripts/python.exe -c "
from agent_local import github_client
from agent_local.polling import pick_candidate_issue, CHAOS_ORIGIN_LABEL

candidates = github_client.list_candidate_issues()
issue = next((c for c in candidates if c.number == $ISSUE_NUMBER), None)
assert issue is not None, 'issue de teste nao apareceu como candidata crua - algo mudou no filtro base (label/assignee)'
assert CHAOS_ORIGIN_LABEL in issue.labels, 'issue de teste sem a label esperada'

picked = pick_candidate_issue()
assert picked is None or picked.number != $ISSUE_NUMBER, 'FALHA: pick_candidate_issue escolheu a issue de caos'
print('OK: issue de caos estava entre as candidatas cruas e foi pulada.')
print('pick_candidate_issue() escolheu:', picked.number if picked else None)
"
cd ..

echo "== [6/6] Limpeza: fecha a issue de teste e resolve o sinal em agent_ops =="
gh issue close "$ISSUE_NUMBER" -c "Issue de teste criada por scripts/validate_chaos_pipeline_e2e.sh (validacao de ponta a ponta real do filtro de caos). Fechando como artefato de teste."
docker exec bank-of-decoy-postgres psql -U bank -d agent_ops -c "UPDATE flagged_signals SET resolved_at = now(), updated_at = now() WHERE issue_number = $ISSUE_NUMBER;"

echo
echo "Validacao concluida. Issue #$ISSUE_NUMBER fechada, caos desligado, sinal resolvido em agent_ops."
