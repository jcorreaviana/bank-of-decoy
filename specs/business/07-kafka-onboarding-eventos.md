# 07 — Onboarding orientado a eventos via Kafka

## Contexto / objetivo
Substituir a consulta síncrona REST introduzida em [05-account-post-sincrono.md](05-account-post-sincrono.md) por um fluxo assíncrono orientado a eventos: o onboarding-service publica o resultado da classificação de risco (história [04-onboarding-risco.md](04-onboarding-risco.md)) como evento Kafka, e os consumidores interessados (account-service, filas de revisão) reagem a ele. Isso desacopla os serviços e introduz o padrão de mensageria que as próximas fases (chaos, agentes) vão explorar.

## Contrato afetado

### Eventos publicados pelo onboarding-service
Tópico `onboarding.aprovado`, `onboarding.reprovado_qualidade`, `onboarding.reprovado_fraude` (um tópico por resultado, conforme [messaging.md](../tech/messaging.md)).

Envelope (formato padrão de [messaging.md](../tech/messaging.md)):
```json
{
  "event_id": "UUID",
  "event_type": "onboarding.aprovado | onboarding.reprovado_qualidade | onboarding.reprovado_fraude",
  "occurred_at": "timestamp",
  "payload": {
    "onboarding_id": "UUID",
    "motivo_reprovacao": "string|null"
  }
}
```
- `payload` nunca inclui CPF, nome ou outro dado pessoal — apenas `onboarding_id`, conforme [security.md](../tech/security.md).

### Consumo pelo account-service
- Consome `onboarding.aprovado` e cria a conta correspondente (mesma regra de idempotência de [05-account-post-sincrono.md](05-account-post-sincrono.md): não duplica conta para o mesmo `onboarding_id`).
- `POST /v1/accounts` (endpoint síncrono da história 05) é removido ou passa a ser rota interna apenas para reprocessamento manual — o fluxo principal de criação de conta deixa de depender de chamada REST síncrona ao onboarding-service.

### Filas de revisão
- `onboarding.reprovado_qualidade` alimenta uma fila de revisão de qualidade **com retentativa**: falha de processamento é reenfileirada (dead-letter após N tentativas, N definido na implementação).
- `onboarding.reprovado_fraude` alimenta uma fila de revisão de compliance **sem retentativa**: falha de processamento não é reenfileirada automaticamente — decisão de compliance exige revisão manual, reprocessamento automático poderia mascarar um caso de fraude não tratado.

## Critério de aceite
- [ ] Onboarding classificado como `aprovado` publica evento em `onboarding.aprovado` com envelope completo e correto.
- [ ] Onboarding classificado como `reprovado_qualidade` ou `reprovado_fraude` publica no tópico correspondente.
- [ ] Evento só é publicado após o commit da transação que persistiu o `status` no banco (nunca antes — ver [messaging.md](../tech/messaging.md)).
- [ ] `payload` do evento não contém CPF, nome, e-mail ou telefone.
- [ ] account-service consumindo `onboarding.aprovado` cria a conta e é idempotente: reprocessar o mesmo `event_id` não cria conta duplicada.
- [ ] Fila de qualidade reprocessa automaticamente uma falha simulada de consumo (ex. exceção no handler) até sucesso ou até o limite de tentativas.
- [ ] Fila de fraude/compliance não reprocessa automaticamente uma falha simulada — mensagem falha permanece visível para intervenção manual (ex. dead-letter direto, sem retry).
- [ ] `POST /v1/accounts` síncrono da história 05 deixa de ser o caminho usado pelo funil principal (removido ou redocumentado como rota de reprocessamento manual).
- [ ] Teste de contrato/integração cobre: publicação do evento correto por resultado de classificação, consumo idempotente, e o comportamento diferenciado de retry entre as duas filas.

## Specs técnicas aplicáveis
- [messaging.md](../tech/messaging.md) — nomenclatura de tópico, envelope de evento, idempotência.
- [security.md](../tech/security.md) — PII fora do payload do evento.
- [observability.md](../tech/observability.md) — `trace_id` propagado no envelope do evento para correlação com logs/métricas.
