"""Bootstrap/polling do consumidor Kafka de `onboarding.aprovado` - infra
de conexao (mesma categoria de app/core/db.py: fora da exigencia de
cobertura de specs/tech/testing.md). A regra de negocio testavel (o que
fazer com o envelope) vive em app/services/onboarding_event_consumer.py.
"""

import json
import logging
import threading
import traceback

from confluent_kafka import Consumer

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.services.onboarding_event_consumer import TOPIC, process_onboarding_aprovado_envelope

logger = logging.getLogger(__name__)

GROUP_ID = "account-service-onboarding-aprovado"
_POLL_TIMEOUT_SECONDS = 1.0


def _handle_message(consumer: Consumer, msg) -> None:
    raw_value = msg.value()
    try:
        envelope = json.loads(raw_value.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        # Mensagem ilegivel nunca vai processar em uma proxima tentativa -
        # commitamos para nao travar o consumo em um "poison pill", mas o
        # erro fica bem visivel no log (nunca um descarte silencioso).
        logger.error(
            "Payload de evento invalido em onboarding.aprovado - mensagem descartada apos falha de parse.",
            extra={"context": {"erro": str(exc), "raw_length": len(raw_value or b"")}},
        )
        consumer.commit(message=msg)
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
    except Exception:
        db.rollback()
        # Offset NAO commitado de proposito - falha de consumo fica visivel
        # no log (stack trace completo), nunca descartada em silencio.
        # Isso NAO garante reentrega incondicional: se uma mensagem
        # POSTERIOR na mesma particao for processada com sucesso antes do
        # consumidor reiniciar, o commit dela avanca o offset do grupo e
        # "engole" esta falha (Kafka comita um numero de offset, nao um
        # conjunto esparso de mensagens individuais) - a mensagem original
        # so e reentregue se o consumidor parar/reiniciar/rebalancear ANTES
        # disso acontecer. Decisao de escopo: um "stop the world" que
        # bloqueia o topico inteiro ate a falha ser resolvida garantiria
        # reentrega sempre, mas trocaria uma falha pontual de uma conta por
        # uma parada de todo o funil - fora de escopo da issue #7 (mesma
        # filosofia de nao construir retry sofisticado ja aplicada em
        # onboarding_internal_client.py/account_client.py). O log ERROR
        # abaixo e, hoje, a garantia real: visibilidade, nao redelivery.
        logger.error(
            "Falha ao processar evento onboarding.aprovado - offset nao commitado.",
            extra={
                "context": {
                    "event_id": envelope.get("event_id"),
                    "stack_trace": traceback.format_exc(),
                }
            },
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

            _handle_message(consumer, msg)
    finally:
        consumer.close()
        logger.info("Consumidor onboarding.aprovado encerrado.", extra={"context": {"topic": TOPIC}})
