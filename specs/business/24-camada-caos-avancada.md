# 24 — Camada de caos avançada (Fase 2b)

## Contexto

A Fase 2 (issue #11) entregou o middleware de caos com 4 tipos de falha (`timeout`, `503`, `500`, `latencia`), validado ponta a ponta com os golden signals do Grafana e já consumido pelo agente preditivo. Esses 4 tipos geram sinais conhecidos e já resolvidos. A Fase 2b estende a camada de caos com cenários que a versão original — falha isolada, HTTP-side, binária — não cobre: falha correlacionada entre serviços (cascata), disrupção do caminho assíncrono via Kafka, e tipos de falha sutis que exigem detecção de padrão/tendência em vez de pico isolado.

## Objetivo

Estender a camada de caos da Fase 2 com cenários que a versão original (falha isolada, HTTP-side, binária) não cobre: falha correlacionada entre serviços (cascata), disrupção do caminho assíncrono via Kafka, e tipos de falha sutis que exigem detecção de padrão/tendência em vez de pico isolado — elevando a exigência sobre o agente preditivo.

## Contrato afetado

Adiciona um endpoint interno por serviço: `POST /internal/chaos/config` (não exposto publicamente, só acessível na rede Docker interna), permitindo ajustar parâmetros de caos em runtime sem restart. Nenhuma mudança nos contratos REST públicos existentes.

## Novos tipos de falha

- `kafka_lag`: consumer processa mensagens com atraso crescente, sem parar de consumir (simula backlog, não perda)
- `kafka_delay`: publish do evento é atrasado antes de chegar ao tópico (simula latência de infraestrutura de mensageria, não do serviço)
- `degradacao_progressiva`: latência que cresce ao longo de uma janela de tempo configurável (ex. rampa de 0 a 3s em 5 minutos), em vez de constante — testa se o agente detecta tendência, não só limiar
- `payload_corrompido_sutil`: payload malformado mas que passa validação superficial (ex. campo numérico como string coercível, campo opcional ausente) — testa se o erro se propaga silenciosamente até causar inconsistência downstream, em vez de falhar explicitamente

## Cascata coordenada

Novo componente `chaos-orchestrator/` (script Python leve, fora dos 4 microsserviços): lê um arquivo de cenário (YAML) descrevendo uma timeline de ativações (qual serviço, qual tipo de falha, em qual minuto, por quanto tempo) e chama o endpoint interno de cada serviço na sequência certa. Permite simular, por exemplo, degradação no account-service enquanto transaction-service está sob carga alta, sem coordenação manual.

## Execução orgânica (janela de validação real)

Assim como na janela de validação da Fase original, a Fase 2b será validada com tráfego sintético e o cenário de caos do `chaos-orchestrator` rodando simultaneamente, com os daemons dos agentes (preditivo, registro, local) ativos organicamente, por 2 horas de relógio.

Regras específicas desta janela:
- Ao final das 2 horas, o gerador de tráfego sintético e o `chaos-orchestrator` param de iniciar novas ações, mas o ambiente permanece no ar.
- Os agentes NÃO são interrompidos no fechamento da janela — se houver issue em processamento (agente local com issue atribuída, agente preditivo em ciclo, PR aguardando gate), eles devem concluir o ciclo normalmente, sem corte abrupto.
- Após os agentes finalizarem toda atividade pendente, o ambiente continua no ar (não fazer `docker-compose down` automaticamente) para coleta de evidências complementares — logs, dashboards Grafana, tabelas de `agent_ops`, issues geradas — destinadas ao repositório e a um artigo sobre a execução.
- Essa etapa de execução é operacional, não faz parte do critério de aceite técnico da issue (o código estar pronto e testado é o que fecha a issue); a janela de 2h é uma atividade separada, feita depois da implementação e do fechamento da issue técnica.

## Critério de aceite

- [ ] Endpoint `POST /internal/chaos/config` implementado nos 4 serviços, aceitando ajuste de tipo/taxa/duração em runtime
- [ ] Os 4 novos tipos de falha implementados e testáveis individualmente
- [ ] `chaos-orchestrator` lê um cenário YAML de exemplo e executa a timeline corretamente contra o ambiente local
- [ ] Cenário de cascata de exemplo (2+ serviços correlacionados) documentado e reproduzível
- [ ] Golden signals no Grafana capturam visivelmente o efeito de `degradacao_progressiva` como tendência, não só como pico
- [ ] Issues geradas pelo agente preditivo a partir desses cenários continuam rotuladas `chaos-test` e ignoradas pelo agente local, mesmo com os novos tipos de falha
- [ ] Documentação de como rodar um cenário de caos avançado manualmente ou via orquestrador, incluindo o modo de execução da janela de 2h (traffic + chaos-orchestrator + parada limpa sem derrubar agentes em atividade)

## Specs técnicas relevantes

- `specs/tech/error-handling.md`
- `specs/tech/logging.md`
- `specs/tech/observability.md`
- `specs/tech/infrastructure.md`
- `specs/tech/messaging.md`
- `specs/tech/security.md` (o endpoint interno precisa estar de fato inacessível externamente)

## Sinal de risco (para o score de subida)

Categoria da mudança: operacional
Serviço(s) afetado(s): os 4 microsserviços + novo componente `chaos-orchestrator` (criticidade conforme já definida por serviço)

## Dependências

Depende da Fase 2 original (issue #11 — middleware de caos já implementado) e da issue de observabilidade (issue #9 — golden signals), ambas já concluídas.
