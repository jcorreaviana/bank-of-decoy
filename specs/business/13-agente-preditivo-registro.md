# 13 — Agente preditivo + agente de registro (Fase 3)

## Contexto

Fase 1 e a infraestrutura de agentes (labels, templates, agent_ops, ambiente efêmero) estão prontas. Esta história implementa os dois primeiros agentes da arquitetura desenhada em `docs/escopo-arquitetura.md`: o agente preditivo (identifica bugs e oportunidades) e o agente de registro (escreve a issue no formato correto).

## Objetivo

**Agente preditivo (Modelo A)**
- Modelo: `llama3.2:3b` via Ollama, local
- Acionamento: polling periódico (definir intervalo, ex. a cada 5 minutos)
- Duas funções de detecção, rodando em cada ciclo:
  1. **Detecção de bug**: consulta Prometheus (golden signals) e logs estruturados. Aplica os thresholds já definidos: taxa de erro > 5% em 5 min por serviço; latência p95 > 2x mediana histórica; saturação de pool de conexão > 80%; log CRITICAL ou ERROR repetido 3+ vezes em 5 min com a mesma mensagem.
  2. **Detecção de oportunidade**: lê specs de negócio (`specs/business/`) via RAG, roda uma bateria de cenários sintéticos contra a API do ambiente efêmero de teste (`docker-compose.test.yml`), verificando se regras já especificadas são realmente respeitadas (ex. saldo insuficiente, chave cancelada). Quando encontra um gap, mapeia e documenta a jornada reproduzível (sequência de chamadas que gerou o comportamento incorreto), salvando como cenário estruturado em `tests/scenarios/`.
- Antes de sinalizar qualquer achado, consulta a tabela `flagged_signals` (database `agent_ops`) para verificar se aquele sinal específico já foi sinalizado e ainda está em aberto — evita duplicar issue para o mesmo problema.

**Agente de registro (Modelo B)**
- Mesmo modelo `llama3.2:3b`, dois system prompts diferentes: um para narrativa técnica (bug), outro para narrativa de negócio (oportunidade), escolhido conforme a classificação do Modelo A
- Usa RAG sobre o template correspondente (`.github/ISSUE_TEMPLATE/bug-report.md` ou `.github/ISSUE_TEMPLATE/business-story.md`) para gerar o conteúdo da issue no formato esperado
- Preenche os campos "Categoria da mudança" e "Serviço(s) afetado(s) e criticidade" — esses campos serão lidos depois pelo agente local para o cálculo do score de risco
- Cria a issue via `gh issue create`, com a label correta (`bug` ou `business-story`)
- Registra o achado na tabela `flagged_signals` (dedup para próximos ciclos)

## Contrato afetado

Nenhum endpoint REST novo. Este agente é um processo Python separado (ex. `agent-preditivo/`), não um microserviço com API própria nesta fase — roda como script/daemon local.

## Critério de aceite

- [ ] Agente preditivo roda em loop de polling configurável, sem erro
- [ ] Detecção de bug funcional: testável ligando `CHAOS_ENABLED` num serviço (mesmo que a implementação de caos em si ainda não exista — pode simular manualmente um cenário de erro elevado para o teste) e confirmando que o agente detecta e classifica corretamente
- [ ] Detecção de oportunidade funcional: roda contra o ambiente efêmero de teste, identifica pelo menos um gap real (se existir) ou confirma ausência de gaps nos cenários testados
- [ ] Deduplicação funcionando: mesmo sinal não gera issue duplicada em execuções consecutivas
- [ ] Agente de registro gera issues corretamente formatadas, com os campos de risco preenchidos, na label correta
- [ ] Cenários de oportunidade mapeados ficam salvos em `tests/scenarios/`, em formato reutilizável
- [ ] Testes automatizados cobrindo a lógica de classificação e o mecanismo de deduplicação

## Specs técnicas relevantes

- `specs/tech/observability.md`
- `specs/tech/database.md`
- `specs/tech/messaging.md` (se aplicável para consumo de contexto)
- `docs/escopo-arquitetura.md` (arquitetura completa dos agentes)

## Sinal de risco (para o score de subida)

Categoria da mudança: regra de negócio (decisão de arquitetura de agentes)
Serviço(s) afetado(s): novo componente (`agent-preditivo`), criticidade a definir — sugestão: alto, por ser peça central da automação

## Dependências

Depende da issue #9 (Grafana/Prometheus), #10 (base de segurança, indiretamente), e da infraestrutura de agentes já implementada (label `bug`, template, `agent_ops`, ambiente efêmero).
