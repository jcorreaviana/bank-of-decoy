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

## Poison message e dead-letter topic (DLT)

Todo consumer Kafka do projeto (hoje: `account-service`, consumindo `onboarding.aprovado`) precisa tratar poison message — uma mensagem que falha permanentemente e nunca teria sucesso em um novo reprocessamento. Sem isso, como o offset não avança em caso de falha (`enable.auto.commit=False`), a mesma mensagem trava o consumer indefinidamente a cada restart do serviço (incidente real, issue #31: mensagens cifradas com uma `CPF_ENCRYPTION_KEY` já rotacionada nunca mais decifravam, e o consumer reprocessava o mesmo lote para sempre).

Implementado no módulo compartilhado `shared/kafka_dlt`, adotado por todo consumer existente hoje.

**Terminologia**: usar sempre **DLT** (dead-letter *topic*), nunca DLQ (dead-letter *queue*) — Kafka trabalha com tópicos, não filas.

### Contador de tentativas via header Kafka

- Header `x-retry-count` (string decimal, ausente = 0) carregado na própria mensagem Kafka — não em memória nem em tabela de banco. Isso é proposital: como o offset da mensagem que falha nunca avança sozinho, o processo pode reiniciar quantas vezes for com a mensagem parada na mesma posição; um contador em memória (ou em uma tabela consultada pelo offset) seria irrelevante ou perdido a cada restart. Guardar o contador dentro da mensagem, reenviada para o fim do tópico original a cada tentativa que falha, resolve isso sem estado adicional.
- A cada falha de processamento, o consumer publica a mesma mensagem (mesma `key`, mesmo `value`, headers originais preservados) de volta no tópico original com `x-retry-count` incrementado, e só então comita o offset da mensagem que falhou — o offset **sempre avança** após uma falha (reenvio ou DLT), nunca fica parado.
- Tradeoff aceito: o reenvio via republicação no fim do tópico não preserva a ordem relativa entre a mensagem que falhou e as mensagens seguintes já publicadas — aceitável nesta fase (mesma filosofia de simplicidade já aplicada a `error-handling.md`/`kafka_consumer.py`: visibilidade e não travar o consumer importam mais que preservar ordenação estrita sob falha).

### Limite de tentativas

- Configurável por serviço via variável de ambiente própria (ex. `KAFKA_MAX_RETRIES` no `account-service`) — lida pelo `app/core/config.py` de cada serviço, nunca hardcoded no módulo compartilhado.
- Default: **3** tentativas (`kafka_dlt.DEFAULT_MAX_RETRIES`).
- `max_retries=0` força ida direta ao DLT, sem nenhum reenvio — usado quando a falha já é reconhecidamente permanente antes mesmo da primeira tentativa de reprocessamento (ex. payload que nem chega a ser JSON válido: reenviar só adiaria o inevitável).
- Falhas do próprio Kafka ao reenviar/publicar (broker inalcançável, fila cheia) **não** contam como poison message — nesse caso a exceção propaga, o offset não é commitado, e a mensagem é reprocessada normalmente quando o consumer se recuperar (é indisponibilidade de infraestrutura, não um problema da mensagem).
- Não há, por ora, distinção entre erro transitório (ex. timeout de banco) e erro permanente (ex. payload malformado) dentro do contador — os dois consomem o mesmo limite de tentativas. Deliberadamente fora de escopo por enquanto (issue #31): priorizar que nenhuma mensagem trave o consumer para sempre, sobre reduzir reprocessamentos desnecessários.

### Convenção de nome do tópico DLT

`{tópico-original}.dlt` — ex. `onboarding.aprovado.dlt`.

### Contrato da mensagem no DLT

Ao atingir o limite de tentativas, a mensagem publicada no tópico `.dlt` preserva:

- `value`: o payload original, **sem modificação** — quem for reprocessar manualmente lê exatamente o mesmo evento que o tópico original carregava.
- `key`: a mesma key da mensagem original.
- `headers`: os headers originais, mais:
  - `x-retry-count`: total de tentativas que falharam (igual ao limite configurado).
  - `x-dlt-original-topic`: nome do tópico de origem.
  - `x-dlt-error`: `"{TipoDaExceção}: {mensagem}"` da falha que causou a última tentativa.
  - `x-dlt-failed-at`: timestamp ISO 8601 UTC de quando a mensagem foi movida para o DLT.

Não há, nesta issue, um consumer de leitura do DLT — o objetivo é só garantir que a mensagem poison para de bloquear o consumer original e fica visível/recuperável em um tópico separado (`kafka-console-consumer`/`kafka-topics` ou equivalente para inspeção manual).
