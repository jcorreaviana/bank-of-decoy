# 14 — Agente local (Fase 4)

## Contexto

O agente preditivo + registro (issue #15, quando implementada) abre issues no board com os campos de risco preenchidos. Esta história implementa o agente local: quem efetivamente pega essas issues, implementa a correção/feature, e decide sobre autonomia de subida via score de risco. É o componente mais exigente em raciocínio da arquitetura, por isso usa Claude Code SDK (dentro do plano Pro) em vez de um modelo local pequeno.

## Objetivo

Implementar um processo (`agent-local/`, script/daemon Python que invoca o Claude Code SDK) com o seguinte fluxo:

1. **Polling**: consulta periodicamente issues abertas com label `business-story` ou `bug`, sem assignee
2. **Verificação de dependências**: lê o campo "Dependências" da issue; se referenciar outra issue ainda aberta, pula para a próxima
3. **Self-assign**: ao escolher uma issue, atribui a si mesmo via `gh issue edit --add-assignee` antes de começar (evita disputa entre ciclos concorrentes)
4. **Implementação**: clona/atualiza o repositório, cria uma branch, lê a issue e a spec de negócio vinculada, invoca o Claude Code SDK com a task de implementação
5. **Testes**: roda a suíte de testes do(s) serviço(s) afetado(s), captura cobertura (`pytest --cov`) e tamanho do diff (`git diff --stat`)
6. **Score de risco**: calcula em código (não delega ao LLM) usando a fórmula já definida em `docs/escopo-arquitetura.md` (seção "Score de risco de subida") — lê os campos "Categoria da mudança" e "Serviço(s) afetado(s) e criticidade" diretamente do corpo da issue, soma com cobertura de teste e tamanho de diff
7. **Registro de auditoria**: grava a decisão na tabela `risk_decisions` (database `agent_ops`) — issue, PR (quando existir), score, threshold usado, decisão, timestamp
8. **Gate**: sempre abre PR (nunca push direto para `main`). Se o score estiver abaixo do threshold do tier de criticidade do serviço, aprova e faz merge sozinho (`gh pr merge`). Se estiver acima, deixa o PR aberto, adiciona a label `needs-human-review`, comenta explicando o score e o racional da decisão, e não faz merge

## Contrato afetado

Nenhum endpoint REST novo. Processo Python separado, sem API própria nesta fase.

## Critério de aceite

- [ ] Agente local roda em loop de polling configurável
- [ ] Self-assign funcional — duas execuções concorrentes não pegam a mesma issue
- [ ] Verificação de dependências funcional — issue com dependência aberta é pulada corretamente
- [ ] Invocação do Claude Code SDK funcional para pelo menos um cenário de teste real (ex. uma issue simples criada manualmente para validar o fluxo ponta a ponta)
- [ ] Score de risco calculado corretamente a partir dos campos da issue + cobertura + diff, batendo com a fórmula documentada
- [ ] Gate funcionando nos dois caminhos: score baixo (merge automático) e score alto (PR aberto, aguardando revisão, sem merge)
- [ ] Registro em `risk_decisions` confirmado para cada execução
- [ ] Testes automatizados cobrindo o cálculo do score e a lógica do gate (não precisa cobrir a invocação real do Claude Code SDK em testes automatizados, pode ser mockado)

## Specs técnicas relevantes

- `specs/tech/database.md`
- `specs/tech/testing.md`
- `docs/escopo-arquitetura.md` (fórmula do score de risco, fluxo completo do agente local)

## Sinal de risco (para o score de subida)

Categoria da mudança: regra de negócio (decisão de arquitetura de agentes, componente que decide autonomia de subida de código)
Serviço(s) afetado(s): novo componente (`agent-local`), criticidade: crítico — este componente decide se código sobe automaticamente para produção, merece o padrão mais alto de revisão

## Dependências

Depende da issue #15 (agente preditivo + registro, para ter issues reais sendo criadas para o agente local consumir) e da infraestrutura de agentes já implementada (`agent_ops`, labels, templates).
