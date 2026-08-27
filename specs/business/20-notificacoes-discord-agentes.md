# 20 — Notificações Discord para eventos dos agentes

## Contexto

Hoje os agentes (preditivo, registro, local) só deixam rastro no GitHub (issues, PRs, comentários) e no `agent_ops` (auditoria), sem notificação ativa. É preciso checar o board manualmente para saber o que está acontecendo. Um canal Discord dedicado, via webhook de entrada, resolve isso com notificação em tempo real e configuração simples (sem necessidade de app/bot approval).

## Objetivo

Notificar um canal Discord dedicado (via webhook de entrada, URL configurada por variável de ambiente `DISCORD_WEBHOOK_URL`) nos seguintes eventos:
1. Agente preditivo abre uma issue nova (bug ou oportunidade) — mensagem com título, label, link da issue
2. Agente local abre um PR aguardando revisão humana (`needs-human-review`) — mensagem com score calculado, threshold, link do PR
3. Agente local faz merge automático — mensagem com issue, score, link do commit/PR mergeado
4. Erro na execução de qualquer um dos agentes (ex. Ollama indisponível, falha ao invocar Claude Code SDK, exceção não tratada no loop) — mensagem de erro com contexto suficiente para diagnóstico

## Objetivo técnico

Módulo compartilhado de notificação (ex. `shared/notifications/`), usado tanto por `agent-preditivo/` quanto por `agent-local/`, evitando duplicar lógica de envio. Implementação via POST HTTP simples ao webhook do Discord (formato de embed do Discord para mensagens bem formatadas, com cor por tipo de evento — ex. verde para merge automático, amarelo para aguardando revisão, vermelho para erro).

## Critério de aceite

- [ ] Módulo de notificação implementado e testável
- [ ] Os 4 eventos disparando notificação corretamente
- [ ] Mensagens com informação suficiente para entender o evento sem precisar abrir o GitHub (mas sempre incluindo o link)
- [ ] Falha ao notificar (ex. Discord indisponível) não deve travar ou quebrar o fluxo principal do agente — logar o erro e seguir
- [ ] `DISCORD_WEBHOOK_URL` documentada em `.env.example` (sem valor real)
- [ ] Testes cobrindo os 4 tipos de notificação (podem mockar a chamada HTTP real)

## Specs técnicas relevantes

- `docs/escopo-arquitetura.md`
- `specs/tech/security.md` (segredo via variável de ambiente, mesma regra já estabelecida)

## Sinal de risco

Categoria da mudança: operacional
Serviço(s) afetado(s): agent-preditivo e agent-local (baixo — não afeta lógica de negócio central)

## Dependências

Depende das issues #15 e #16 (já fechadas).
