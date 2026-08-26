# Observability

## Métricas
- Cada serviço expõe endpoint `GET /metrics` no formato de exposição do Prometheus (`text/plain; version=0.0.4`).
- Grafana consome `/metrics` via scrape do Prometheus configurado para todos os serviços (ver [infrastructure.md](infrastructure.md) para portas).

## Golden signals obrigatórios

| Signal     | Métrica                                  | Tipo      | Labels                          |
|------------|-------------------------------------------|-----------|----------------------------------|
| Latência   | `http_request_duration_seconds`           | histogram | `route`, `method`                |
| Tráfego    | `http_requests_total`                     | counter   | `route`, `method`                |
| Taxa de erro | `http_requests_total` (mesma métrica, filtrada) ou `http_errors_total` | counter | `route`, `method`, `status_code` |
| Saturação  | `db_pool_connections_in_use`              | gauge     | —                                 |

- Latência é medida por rota (path template, ex. `/v1/accounts/{account_id}`, nunca o path com valores reais interpolados — evita explosão de cardinalidade).
- Taxa de erro é derivável do contador de requisições segmentado por `status_code` — não é necessário duplicar em outra métrica se o label já existe.
- Saturação de banco reflete conexões em uso do pool SQLAlchemy vs. tamanho configurado do pool.

## Trace
- `trace_id` (mesmo usado em log, ver [logging.md](logging.md)) é propagado entre serviços via header HTTP `X-Trace-Id` e incluído no envelope de evento Kafka (ver [messaging.md](messaging.md)), permitindo correlacionar métricas, logs e eventos de um mesmo fluxo.

## Health check
- Cada serviço expõe `GET /health` retornando 200 quando o serviço e sua conexão com o banco estão operacionais — usado por orquestração/compose, não é uma métrica Prometheus.
