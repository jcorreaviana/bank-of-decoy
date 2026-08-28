"""Bootstrap/polling do consumidor Kafka de `onboarding.aprovado` - infra
de conexao (mesma categoria de app/core/db.py: fora da exigencia de
cobertura de specs/tech/testing.md). A regra de negocio testavel (o que
fazer com o envelope) vive em app/services/onboarding_event_consumer.py.

Poison message (issue #31, specs/business/22-poison-message-kafka.md):
tratamento delegado ao modulo compartilhado `kafka_dlt` (contador de
tentativas via header Kafka + dead-letter topic apos o limite) - nunca
mais um `except Exception` sem commit deixando o offset preso para
sempre, como no incidente real que originou esta issue.
"""

import json
import logging
import threading

from confluent_kafka import Consumer, KafkaException
from kafka_dlt import get_producer, handle_processing_failure

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.services.onboarding_event_consumer import TOPIC, process_onboarding_aprovado_envelope

logger = logging.getLogger(__name__)

GROUP_ID = "account-service-onboarding-aprovado"
_POLL_TIMEOUT_SECONDS = 1.0


def _handle_message(consumer: Consumer, msg) -> None:
    settings = get_settings()
    raw_value = msg.value()
    try:
        envelope = json.loads(raw_value.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        # Payload que nem chega a ser JSON valido nunca vai suceder em um
        # novo retry - max_retries=0 forca ida direta ao DLT (preserva o
        # payload bruto para investigacao) em vez de descartar em silencio.
        handle_processing_failure(
            producer=get_producer(settings.kafka_bootstrap_servers),
            consumer=consumer,
            msg=msg,
            topic=TOPIC,
            error=exc,
            logger=logger,
            max_retries=0,
        )
        return

    if SessionLocal is None:
        logger.error(
            "DATABASE_URL nao configurada - evento onboarding.aprovado nao pode ser processado agora.",
            extra={"context": {"event_id": envelope.get("event_id")}},
        )
        return  # sem commit: sera reentregue quando o servico tiver banco configurado

    db = SessionLocal()
    try:
        resultado = process_onboarding_aprovado_envelope(db, envelope)
        consumer.commit(message=msg)
        logger.info(
            "Evento onboarding.aprovado processado.",
            extra={"context": {"event_id": envelope.get("event_id"), "resultado": resultado}},
        )
    except Exception as exc:
        db.rollback()
        handle_processing_failure(
            producer=get_producer(settings.kafka_bootstrap_servers),
            consumer=consumer,
            msg=msg,
            topic=TOPIC,
            error=exc,
            logger=logger,
            max_retries=settings.kafka_max_retries,
        )
    finally:
        db.close()


def run_onboarding_aprovado_consumer(stop_event: threading.Event) -> None:
    settings = get_settings()
    consumer = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": GROUP_ID,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([TOPIC])
    logger.info("Consumidor onboarding.aprovado iniciado.", extra={"context": {"topic": TOPIC, "group_id": GROUP_ID}})

    try:
        while not stop_event.is_set():
            msg = consumer.poll(_POLL_TIMEOUT_SECONDS)
            if msg is None:
                continue
            if msg.error():
                logger.error(
                    "Erro ao consumir onboarding.aprovado.",
                    extra={"context": {"kafka_error": str(msg.error())}},
                )
                continue

            try:
                _handle_message(consumer, msg)
            except KafkaException:
                # kafka_dlt so propaga KafkaException quando o proprio
                # Kafka falhou ao reenviar/publicar no DLT (broker
                # inalcancavel, fila cheia) - nao e poison message, e
                # indisponibilidade de infra. O offset desta mensagem nao
                # foi commitado (kafka_dlt garante isso), entao ela sera
                # reprocessada normalmente quando o consumidor se
                # recuperar/reiniciar - sem isso aqui, uma excecao nao
                # tratada mataria a thread do consumidor inteira em
                # silencio (daemon thread, sem supervisor).
                logger.critical(
                    "Falha do Kafka ao lidar com poison message - consumidor segue tentando, "
                    "mensagem atual sera reprocessada.",
                    extra={"context": {"topic": TOPIC}},
                )
    finally:
        consumer.close()
        logger.info("Consumidor onboarding.aprovado encerrado.", extra={"context": {"topic": TOPIC}})
