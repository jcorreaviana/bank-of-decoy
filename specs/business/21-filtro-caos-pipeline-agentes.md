# 21 — Pipeline de agentes deve reconhecer sinais de caos

## Contexto

A camada de caos (issue #13) foi implementada depois do agente preditivo (#15) e do agente local (#16). Diagnóstico confirmou: nenhum dos dois filtra ou reconhece `chaos_injected: true`. O design pretendido (documentado em `docs/escopo-arquitetura.md`, v17) é que o caos continue disparando os thresholds do agente de bug — isso prova que a observabilidade funciona — mas o agente local precisa reconhecer que a issue se origina de caos e não tentar "corrigir" o middleware.

## Objetivo

1. `agent-preditivo`: filtrar logs marcados `chaos_injected: true` na contagem de erro repetido (`logs_client.py`), evitando poluir o sinal com ruído esperado
2. `agent-preditivo`: ao detectar sinal de bug enquanto `CHAOS_ENABLED` está ativo no serviço afetado, marcar a issue criada com indicação clara de origem em caos (ex. label dedicada `chaos-test`, ou campo explícito no corpo da issue)
3. `agent-local`: `pick_candidate_issue` deve pular issues marcadas como originadas de caos — não tentar "corrigir" nada nelas

## Critério de aceite

- [ ] Log com `chaos_injected: true` não conta para o threshold de erro repetido
- [ ] Issue de bug criada durante caos ativo é marcada como tal (visível no corpo/label)
- [ ] Agente local pula issues marcadas como originadas de caos
- [ ] Teste cobrindo o cenário completo: caos ativo → agente preditivo detecta → issue marcada → agente local pula, não tenta corrigir

## Sinal de risco

Categoria da mudança: operacional (correção de comportamento do pipeline de agentes)
Serviço(s) afetado(s): agent-preditivo e agent-local (crítico — evita reversão indevida de código real)

## Dependências

Depende das issues #13, #15, #16 (todas fechadas).
