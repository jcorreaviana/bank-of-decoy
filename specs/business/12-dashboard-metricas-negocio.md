# 12 — Dashboard de métricas de negócio (futuro)

## Contexto

O dashboard atual no Grafana (issue #9) cobre golden signals de engenharia (latência, tráfego, erro, saturação). Falta um dashboard voltado a métricas de negócio — volume de onboarding/contas/transações, percentual de reprovação e suspeita ao longo do tempo, distribuição de sinais de risco. O schema atual (`risco_score`, `risco_sinais`, status de cada entidade) já contempla os dados necessários; falta só construir a visualização.

## Objetivo

Um dashboard Grafana separado (ou uma nova pasta/seção dentro do Grafana existente) mostrando métricas de negócio, consultando diretamente o Postgres (não o Prometheus, já que são dados de domínio, não métricas de sistema).

## Contrato afetado

Nenhum contrato REST novo. Requer datasource Postgres configurado no Grafana (além do Prometheus já existente), com queries SQL para os painéis.

## Critério de aceite (a definir com mais detalhe quando a issue for priorizada)

- [ ] Datasource Postgres configurado no Grafana
- [ ] Painel de volume: onboardings/contas/transações criados por período
- [ ] Painel de percentual de reprovação/suspeita ao longo do tempo (onboarding e transação)
- [ ] Painel de distribuição de sinais de risco mais frequentes

## Specs técnicas relevantes

- `specs/tech/observability.md`
- `specs/tech/database.md`

## Sinal de risco (para o score de subida)

Categoria da mudança: operacional
Serviço(s) afetado(s): infraestrutura/observabilidade (criticidade baixa)

## Dependências

Depende da issue #9 (Grafana já configurado) e da issue #8 (dataset existente para ter dados reais a visualizar). Sem data de priorização definida — fica registrada para quando for retomada.
