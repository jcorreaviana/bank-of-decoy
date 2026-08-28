# 23 — Agentes devem logar no caminho de sucesso silencioso

## Contexto

Achado durante a validação de ponta a ponta da issue #29: `agent-preditivo` (`bug_detection.py`, `registration_agent.py`) e `agent-local` (`polling.py`) não emitem nenhum log em `INFO` quando um ciclo termina sem achado ou quando uma issue é corretamente pulada — só logam em caso de erro. Isso viola a convenção de `specs/tech/logging.md` ("INFO: eventos de negócio relevantes e esperados... um INFO por marco de fluxo") e dificultou a observação em tempo real durante a validação (precisei consultar o GitHub diretamente em vez de confiar nos logs dos próprios processos).

## Objetivo

Adicionar log `INFO` por ciclo nos dois agentes, cobrindo os caminhos de sucesso hoje silenciosos.

## Critério de aceite

- [ ] `agent-preditivo`: log INFO ao final de cada ciclo de detecção (ex. "ciclo concluído, nenhum sinal encontrado" ou "sinal X detectado para o serviço Y")
- [ ] `agent-local`: log INFO quando nenhuma issue candidata é encontrada, e quando uma issue é pulada por dependência aberta ou por ser originada de caos (ex. "issue #N pulada: chaos-test")
- [ ] Logs seguem o formato de `specs/tech/logging.md` (campos obrigatórios, trace_id quando aplicável)

## Sinal de risco

Categoria da mudança: operacional (observabilidade)
Serviço(s) afetado(s): agent-preditivo e agent-local (baixo)

## Dependências

Nenhuma bloqueante. Relacionada à issue #29.
