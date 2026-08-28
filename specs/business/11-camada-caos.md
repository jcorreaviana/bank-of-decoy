# 11 — Camada de caos e resiliência (Fase 2)

## Contexto

A Fase 1 entregou os 4 microserviços funcionais, com observabilidade (Prometheus/Grafana), fluxo orientado a eventos (Kafka) e o dataset de volumetria completo. A Fase 2 introduz falhas técnicas intencionais para testar resiliência, e serve como validação de ponta a ponta da arquitetura de agentes (Fase 3-4): ligar o caos deve disparar os thresholds do agente de bug já definidos no documento de escopo.

## Objetivo

Cada um dos 4 microserviços ganha um middleware de injeção de falha, com toggle independente por serviço — permitindo cenários simples (um serviço falhando) ou complexos (falha em cascata entre múltiplos serviços dependentes).

## Contrato afetado

Nenhuma mudança nos contratos REST existentes. A mudança é transversal: um middleware que intercepta requisições antes do processamento normal, condicionado a configuração de ambiente.

## Configuração

Variáveis de ambiente por serviço:
- `CHAOS_ENABLED` (true/false, default false)
- `CHAOS_FAILURE_RATE` (float, 0.05 a 0.10, probabilidade de injeção por requisição)
- `CHAOS_FAILURE_TYPES` (lista separada por vírgula: `timeout,503,500,latencia`)

## Tipos de falha

- `timeout`: atraso longo o suficiente para estourar timeout do cliente (não retorna resposta dentro do tempo esperado)
- `503`: retorna "Service Unavailable" imediatamente, sem processar a requisição
- `500`: lança uma exceção não tratada, testando o middleware de `error-handling.md` e o log estruturado real
- `latencia`: adiciona atraso mas processa a requisição normalmente (simula degradação de performance, não falha completa)

## Critério de aceite

- [x] Middleware de caos implementado nos 4 serviços, com toggle independente por serviço via variável de ambiente
- [x] Os 4 tipos de falha implementados e testáveis individualmente
- [x] `CHAOS_ENABLED=false` é o padrão — nenhum serviço injeta falha sem configuração explícita
- [ ] Ligar `CHAOS_ENABLED=true` com `CHAOS_FAILURE_RATE` alto (ex. 0.5, só para teste) em um serviço gera taxa de erro/latência visível no dashboard Grafana, confirmando que os golden signals capturam o comportamento — validado via API do Prometheus (aguardando confirmação visual do usuário no Grafana antes de marcar)
- [x] Testes automatizados confirmam que, com o caos desligado, o comportamento normal do serviço não é afetado
- [x] Documentação clara (README ou spec) de como ativar cada tipo de falha, para uso manual ou pela bateria de validação de agentes

## Specs técnicas relevantes

- `specs/tech/error-handling.md`
- `specs/tech/logging.md`
- `specs/tech/observability.md`
- `specs/tech/infrastructure.md`

## Sinal de risco (para o score de subida)

Categoria da mudança: operacional
Serviço(s) afetado(s): os 4 microserviços (criticidade conforme já definida por serviço no documento de escopo)

## Dependências

Depende da issue #9 (observabilidade — os golden signals precisam existir para validar o efeito do caos) e da issue #7 (Kafka — para testar cenários de falha envolvendo o fluxo assíncrono).
