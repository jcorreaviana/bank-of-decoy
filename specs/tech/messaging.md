# Messaging

## Broker
Kafka (+ Zookeeper se a versão do Kafka em uso exigir — ver [infrastructure.md](infrastructure.md)).

## Nomenclatura de tópico
- Formato: `{dominio}.{evento}`, `snake_case`.
- `dominio`: nome do domínio de negócio, não o nome do serviço (ex. `onboarding`, `conta`, `pix`, `transacao`).
- `evento`: fato de negócio já ocorrido, no particípio/passado (ex. `aprovado`, `criada`, `registrada`, `concluida`).
- Exemplos: `onboarding.aprovado`, `conta.criada`, `pix.chave_registrada`, `transacao.concluida`, `transacao.estornada`.

## Envelope padrão de evento

Todo evento publicado segue este formato:

```json
{
  "event_id": "UUID",
  "event_type": "string",
  "occurred_at": "timestamp ISO 8601 UTC",
  "payload": { }
}
```

- `event_id`: UUID único do evento, gerado no momento da publicação — usado para deduplicação por consumidores.
- `event_type`: mesmo valor do nome do tópico ou uma variante mais específica quando o tópico agrupa mais de um tipo de evento (ex. tópico `conta.status_alterado` com `event_type: "conta.bloqueada"` ou `"conta.reativada"`).
- `occurred_at`: momento em que o fato de negócio ocorreu (não necessariamente o momento da publicação, se houver delay).
- `payload`: dados específicos do evento — schema próprio por `event_type`, documentado na spec de negócio correspondente.

## Idempotência
- Todo consumidor é idempotente: mantém registro dos `event_id` já processados (tabela `processed_events` ou equivalente) e ignora reprocessamento do mesmo `event_id`.
- Deduplicação é responsabilidade do consumidor, não do broker — Kafka não garante exactly-once entre serviços nesta arquitetura.

## Produção
- Publicação de evento ocorre após commit da transação de banco que originou o fato (nunca antes) — evita publicar evento de algo que não foi persistido.
