---
name: Bug (detectado pelo agente preditivo)
about: Template para problemas técnicos/operacionais identificados via monitoramento
title: "[BUG] Título curto do problema"
labels: ["bug"]
---

## Sinal que disparou

Qual threshold foi violado (ex. "taxa de erro > 5% em 5 min", "latência p95 > 2x mediana", "saturação de pool > 80%", "log CRITICAL/ERROR repetido 3x+").

## Serviço afetado

Nome do serviço e criticidade (crítico | alto | baixo, conforme documento de escopo).

## Evidência

Trecho relevante de log estruturado ou métrica que embasou a detecção.

## Passos de reprodução (se aplicável)

Sequência de ações que reproduz o comportamento observado, se identificável.

## Sinal de risco (para o score de subida)

Categoria da mudança: operacional (a maioria dos bugs técnicos se enquadra aqui, salvo indicação contrária)
Serviço(s) afetado(s) e criticidade: preencher conforme acima

## Dependências

Issues relacionadas, se houver.
