# 07 — Onboarding orientado a eventos via Kafka

## Contexto / objetivo
Substituir a consulta síncrona REST introduzida em [05-account-post-sincrono.md](05-account-post-sincrono.md) por um fluxo assíncrono orientado a eventos: o onboarding-service publica o resultado da classificação de risco (história [04-onboarding-risco.md](04-onboarding-risco.md)) como evento Kafka, e os consumidores interessados (account-service, filas de revisão) reagem a ele. Isso desacopla os serviços e introduz o padrão de mensageria que as próximas fases (chaos, agentes) vão explorar.

## Contrato afetado

### Eventos publicados pelo onboarding-service
Tópico `onboarding.aprovado`, `onboarding.reprovado_qualidade`, `onboarding.reprovado_fraude` (um tópico por resultado, conforme [messaging.md](../tech/messaging.md)).

Envelope (formato padrão de [messaging.md](../tech/messaging.md), com `trace_id` adicional propagado do request que originou a classificação — ver [observability.md](../tech/observability.md)):
```json
{
  "event_id": "UUID",
  "event_type": "onboarding.aprovado | onboarding.reprovado_qualidade | onboarding.reprovado_fraude",
  "occurred_at": "timestamp",
  "trace_id": "UUID",
  "payload": {
    "onboarding_id": "UUID",
    "risco_score": "number|null",
    "risco_sinais": ["string", "..."],
    "cpf": "string (cifrado, apenas em onboarding.aprovado)",
    "motivo_reprovacao": "string|null (apenas em reprovado_qualidade/reprovado_fraude)"
  }
}
```

**Decisão de implementação (diverge do desenho original acima)**: `onboarding.aprovado` carrega `cpf` **cifrado** (mesmo ciphertext Fernet da coluna `onboardings.cpf`, nunca decifrado pelo onboarding-service) além de `risco_score`/`risco_sinais`, para o account-service criar a conta sem nenhuma chamada de rede de volta ao onboarding-service — o desenho inicial (só `onboarding_id`) exigiria uma consulta síncrona pós-evento, o que reintroduziria o acoplamento que esta história existe para remover. "`payload` nunca inclui CPF... conforme [security.md](../tech/security.md)" é entendido como "nunca em texto claro" — mesma exceção já concedida ao `GET /v1/onboarding/{id}/internal` (ver [03-onboarding-post.md](03-onboarding-post.md)). Eventos de reprovação não carregam `cpf` (nenhum consumidor precisa dele).

### Consumo pelo account-service
- Consome `onboarding.aprovado` e cria a conta correspondente (mesma regra de idempotência de [05-account-post-sincrono.md](05-account-post-sincrono.md): não duplica conta para o mesmo `onboarding_id`), **mais** idempotência por `event_id` (tabela `processed_events`, conforme [messaging.md](../tech/messaging.md)) — protege contra reentrega do mesmo evento pelo Kafka, independente da idempotência por `onboarding_id`.
- `tipo_conta` (campo do `POST /v1/accounts` original) não existe no payload do evento — a criação automática usa o default `"corrente"`, documentado em `app/services/account_service.py::create_account_from_event`. Troca de tipo de conta é decisão de implementação futura, fora do escopo desta história.
- `POST /v1/accounts` (endpoint síncrono da história 05) passa a ser rota **operacional de reprocessamento manual** — não é mais o caminho do funil principal, mas continua fazendo a mesma checagem de aprovação (via `GET /v1/onboarding/{id}/internal`, chamada síncrona mantida apenas aqui) antes de criar a conta, para nunca virar um atalho que pula a regra de negócio.

### Filas de revisão
- `onboarding.reprovado_qualidade` (tópico de resultado) **também** publica no tópico `onboarding.revisao_qualidade` — mesmo evento (mesmo `event_id`), fila dedicada para uma futura rotina de revisão manual **com retentativa**: falha de processamento é reprocessada (dead-letter após N tentativas, N definido na implementação).
- `onboarding.reprovado_fraude` (tópico de resultado) **também** publica no tópico `onboarding.revisao_compliance` — fila dedicada **sem retentativa**: falha de processamento não é reprocessada automaticamente (dead-letter direto) — decisão de compliance exige revisão manual, reprocessamento automático poderia mascarar um caso de fraude não tratado.
- Escopo desta história: o topico existe, recebe o evento, e a lógica de retentativa-vs-dead-letter existe como utilitário testado isoladamente (`app/services/review_retry.py`, onboarding-service) — uma rotina de revisão manual sempre ativa (consumidor de produção, UI de triagem) fica para uma próxima história.

## Critério de aceite
- [x] Onboarding classificado como `aprovado` publica evento em `onboarding.aprovado` com envelope completo e correto.
- [x] Onboarding classificado como `reprovado_qualidade` ou `reprovado_fraude` publica no tópico correspondente.
- [x] Evento só é publicado após o commit da transação que persistiu o `status` no banco (nunca antes — ver [messaging.md](../tech/messaging.md)).
- [x] `payload` do evento não contém CPF **em texto claro** (nem nome, e-mail ou telefone em nenhuma forma) — `cpf` viaja cifrado em `onboarding.aprovado`, decisão de implementação documentada acima.
- [x] account-service consumindo `onboarding.aprovado` cria a conta e é idempotente: reprocessar o mesmo `event_id` não cria conta duplicada.
- [x] Fila de qualidade reprocessa automaticamente uma falha simulada de consumo (ex. exceção no handler) até sucesso ou até o limite de tentativas.
- [x] Fila de fraude/compliance não reprocessa automaticamente uma falha simulada — mensagem falha permanece visível para intervenção manual (ex. dead-letter direto, sem retry).
- [x] `POST /v1/accounts` síncrono da história 05 deixa de ser o caminho usado pelo funil principal (redocumentado como rota de reprocessamento manual).
- [x] Teste de contrato/integração cobre: publicação do evento correto por resultado de classificação, consumo idempotente, e o comportamento diferenciado de retry entre as duas filas.

## Specs técnicas aplicáveis
- [messaging.md](../tech/messaging.md) — nomenclatura de tópico, envelope de evento, idempotência.
- [security.md](../tech/security.md) — PII fora do payload do evento.
- [observability.md](../tech/observability.md) — `trace_id` propagado no envelope do evento para correlação com logs/métricas.
