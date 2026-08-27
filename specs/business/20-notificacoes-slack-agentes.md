# 20 — Notificações Slack para eventos dos agentes

## Contexto

Hoje os agentes (preditivo, registro, local) só deixam rastro no GitHub (issues, PRs, comentários) e no `agent_ops` (auditoria), sem notificação ativa. É preciso checar o board manualmente para saber o que está acontecendo. Um canal Slack dedicado resolve isso com notificação em tempo real.

## Objetivo

Notificar um canal Slack dedicado (ex. `#bank-of-decoy-agents`) nos seguintes eventos:
1. Agente preditivo abre uma issue nova (bug ou oportunidade) — mensagem com título, label, link da issue
2. Agente local abre um PR aguardando revisão humana (`needs-human-review`) — mensagem com score calculado, threshold, link do PR
3. Agente local faz merge automático — mensagem com issue, score, link do commit/PR mergeado
4. Erro na execução de qualquer um dos agentes (ex. Ollama indisponível, falha ao invocar Claude Code SDK, exceção não tratada no loop) — mensagem de erro com contexto suficiente para diagnóstico

## Objetivo técnico

Módulo compartilhado de notificação (ex. `shared/notifications/`), usado tanto por `agent-preditivo/` quanto por `agent-local/`, evitando duplicar lógica de envio.

## Critério de aceite

- [ ] Módulo de notificação implementado e testável
- [ ] Os 4 eventos disparando notificação corretamente
- [ ] Mensagens com informação suficiente para entender o evento sem precisar abrir o GitHub (mas sempre incluindo o link)
- [ ] Falha ao notificar (ex. Slack indisponível) não deve travar ou quebrar o fluxo principal do agente — logar o erro e seguir
- [ ] Testes cobrindo os 4 tipos de notificação (podem mockar a chamada real ao Slack)

## Specs técnicas relevantes

- `docs/escopo-arquitetura.md`

## Sinal de risco

Categoria da mudança: operacional
Serviço(s) afetado(s): agent-preditivo e agent-local (baixo — não afeta lógica de negócio central)

## Dependências

Depende das issues #15 e #16 (já fechadas).
