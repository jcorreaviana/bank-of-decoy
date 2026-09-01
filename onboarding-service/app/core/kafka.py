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
        key = msg.key()
        logger.error(
            "Falha na entrega do evento Kafka.",
            extra={
                "context": {
                    "topic": msg.topic(),
                    "key": key.decode("utf-8") if key else None,
                    "error": str(err),
                }
            },
        )


def publish_event(topic: str, envelope: dict, key: str | None = None) -> None:
    """Publica um unico `envelope` (ja serializavel) em `topic`. Atalho de
    `publish_events` para o caso de um evento so - ver ali para o
    comportamento de bloqueio/flush."""
    publish_events([(topic, envelope, key)])


def publish_events(events: list[tuple[str, dict, str | None]]) -> None:
    """Publica um ou mais eventos (mesmo fato de negocio ou nao) com um
    UNICO flush ao final. Bloqueia ate os delivery reports chegarem (ou
    `_FLUSH_TIMEOUT_SECONDS` esgotar) - falha ou timeout ficam visiveis via
    log ERROR, nunca descartados em silencio.

    Issue #69 (latencia_alta no onboarding-service): `publish_onboarding_classified`
    publicava o mesmo fato de negocio em dois topicos (resultado + fila de
    revisao) chamando produce+flush duas vezes em sequencia - cada flush
    bloqueia ate a confirmacao de entrega, entao dois flushes sequenciais no
    mesmo request dobravam o tempo de round-trip com o broker no caminho de
    reprovacao (qualidade/fraude). Produzir as N mensagens primeiro e so
    entao flushar uma vez faz o broker confirmar as entregas em paralelo,
    nao em serie.

    Chaos `kafka_delay` (issue #52, specs/business/24-camada-caos-avancada.md):
    atraso fixo aplicado antes de cada produce - simula latencia da
    infraestrutura de mensageria, nao do servico em si."""
    if not events:
        return

    producer = get_producer()
    produced_any = False
    for topic, envelope, key in events:
        delay = maybe_kafka_publish_delay_seconds()
        if delay:
            time.sleep(delay)

        try:
            producer.produce(
                topic,
                key=key.encode("utf-8") if key else None,
                value=json.dumps(envelope).encode("utf-8"),
                callback=_delivery_callback,
            )
            produced_any = True
        except KafkaException as exc:
            logger.error(
                "Excecao ao publicar evento Kafka.",
                extra={"context": {"topic": topic, "event_id": envelope.get("event_id"), "error": str(exc)}},
            )

    if not produced_any:
        return

    pending = producer.flush(timeout=_FLUSH_TIMEOUT_SECONDS)
    if pending > 0:
        logger.error(
            "Evento Kafka nao confirmado como entregue dentro do timeout.",
            extra={
                "context": {
                    "topicos": [topic for topic, _envelope, _key in events],
                    "mensagens_pendentes": pending,
                }
            },
        )
