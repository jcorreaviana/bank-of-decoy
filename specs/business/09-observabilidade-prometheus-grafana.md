# 09 — Instrumentação de observabilidade (Prometheus + Grafana)

## Contexto

Os quatro microserviços (issue #1) sobem localmente e respondem `/health`, mas ainda não expõem métricas. Sem isso, não há golden signals disponíveis para o Grafana, e o agente preditivo (Fase 3) não tem sinal de sistema para monitorar. Fecha a lacuna de observabilidade antes de avançar para os endpoints de domínio.

## Objetivo

Cada serviço expõe `/metrics` no formato Prometheus. Prometheus coleta essas métricas. Grafana visualiza via dashboard com os golden signals.

## Contrato afetado

Referencia `specs/tech/observability.md`: golden signals obrigatórios por serviço — latência (histograma por rota), tráfego (contador de requisições), taxa de erro (contador por status code), saturação (uso de conexões do pool de banco).

Endpoint novo em cada serviço:
```
GET /metrics
  resposta 200: formato texto Prometheus (content-type: text/plain; version=0.0.4)
```

## Infraestrutura

Adicionar ao `docker-compose.yml` da raiz:
- Serviço `prometheus`, com `prometheus.yml` configurado para fazer scrape dos 4 serviços (portas 8001-8004, endpoint `/metrics`)
- Serviço `grafana`, com datasource Prometheus pré-configurado (provisioning), porta padrão 3000

## Critério de aceite

- [ ] Os quatro serviços expõem `/metrics` com os 4 golden signals
- [ ] Prometheus sobe via docker-compose e faz scrape com sucesso dos 4 serviços (visível em `http://localhost:9090/targets`)
- [ ] Grafana sobe via docker-compose, com datasource Prometheus já conectado (sem configuração manual)
- [ ] Um dashboard inicial no Grafana (pode ser provisionado via JSON) mostrando os 4 golden signals dos 4 serviços
- [ ] `docker-compose up` sobe todo o stack (Postgres + Prometheus + Grafana + serviços) sem erro

## Specs técnicas relevantes

- `specs/tech/observability.md`
- `specs/tech/infrastructure.md`
- `specs/tech/stack.md`

## Sinal de risco (para o score de subida)

Categoria da mudança: operacional
Serviço(s) afetado(s): infraestrutura/observabilidade (criticidade baixa)

## Dependências

Depende da issue #1 (setup do monorepo).
