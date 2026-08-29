"""Producer Kafka compartilhado (specs/tech/messaging.md).

Um unico Producer por processo (confluent-kafka gerencia sua propria fila
de entrega e thread de I/O internamente - criar um por publicacao seria
desperdicio). `publish_event` bloqueia ate a confirmacao de entrega (ou
timeout) porque, nesta fase, publicacao e best-effort e sincrona: se o
Kafka estiver indisponivel, queremos que a falha apareca no log da mesma
request/commit que gerou o evento, nao silenciosamente mais tarde.
"""

import json
import logging
import time

from chaos import maybe_kafka_publish_delay_seconds
from confluent_kafka import KafkaException, Producer

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_FLUSH_TIMEOUT_SECONDS = 10.0

_producer: Producer | None = None


def get_producer() -> Producer:
    global _producer
    if _producer is None:
        settings = get_settings()
        _producer = Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})
    return _producer


def _delivery_callback(err, msg) -> None:
    if err is not None:
        logger.error(
            "Falha na entrega do evento Kafka.",
            extra={"context": {"topic": msg.topic(), "error": str(err)}},
        )


def publish_event(topic: str, envelope: dict, key: str | None = None) -> None:
    """Publica `envelope` (ja serializavel) em `topic`. Bloqueia ate o
    delivery report chegar (ou `_FLUSH_TIMEOUT_SECONDS` esgotar) - falha ou
    timeout ficam visiveis via log ERROR, nunca descartados em silencio.

    Chaos `kafka_delay` (issue #52, specs/business/24-camada-caos-avancada.md):
    atraso fixo aplicado aqui, antes do produce - simula latencia da
    infraestrutura de mensageria, nao do servico em si."""
    delay = maybe_kafka_publish_delay_seconds()
    if delay:
        time.sleep(delay)

    producer = get_producer()
    try:
        producer.produce(
            topic,
            key=key.encode("utf-8") if key else None,
            value=json.dumps(envelope).encode("utf-8"),
            callback=_delivery_callback,
        )
        pending = producer.flush(timeout=_FLUSH_TIMEOUT_SECONDS)
    except KafkaException as exc:
        logger.error(
            "Excecao ao publicar evento Kafka.",
            extra={"context": {"topic": topic, "event_id": envelope.get("event_id"), "error": str(exc)}},
        )
        return

    if pending > 0:
        logger.error(
            "Evento Kafka nao confirmado como entregue dentro do timeout.",
            extra={
                "context": {
                    "topic": topic,
                    "event_id": envelope.get("event_id"),
                    "mensagens_pendentes": pending,
                }
            },
        )
