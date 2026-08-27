"""Processamento do evento `onboarding.aprovado` (specs/business/07-kafka-onboarding-eventos.md).

Substitui a chamada REST sincrona da issue #5 como caminho PRINCIPAL de
criacao de conta: o account-service reage ao evento em vez de esperar uma
requisicao HTTP direta. `process_onboarding_aprovado_envelope` e a logica
pura (sem Kafka, sem thread) - testada isoladamente contra um banco real,
chamando-a duas vezes com o mesmo envelope para provar a idempotencia por
`event_id` (specs/tech/messaging.md) sem precisar de um broker de verdade
no teste. O polling real do topico vive em app/core/kafka_consumer.py
(infra/bootstrap, mesma categoria de app/core/db.py - fora da exigencia de
cobertura de specs/tech/testing.md)."""

import logging
import uuid

from sqlalchemy.orm import Session

from app.core.errors import AccountAlreadyExistsError
from app.repositories import processed_event_repository
from app.services.account_service import create_account_from_event

logger = logging.getLogger(__name__)

TOPIC = "onboarding.aprovado"


def process_onboarding_aprovado_envelope(db: Session, envelope: dict) -> str:
    """Retorna "conta_criada", "conta_ja_existia" (idempotencia por
    `onboarding_id`, defesa redundante ao lado da idempotencia por
    `event_id` abaixo) ou "duplicado_ignorado" (idempotencia por
    `event_id` - reentrega do mesmo evento pelo Kafka)."""
    event_id = envelope["event_id"]

    if processed_event_repository.is_processed(db, event_id):
        logger.info(
            "Evento onboarding.aprovado ja processado, ignorando (idempotencia por event_id).",
            extra={"context": {"event_id": event_id}},
        )
        return "duplicado_ignorado"

    payload = envelope["payload"]
    onboarding_id = uuid.UUID(payload["onboarding_id"])

    try:
        create_account_from_event(db, onboarding_id, payload)
        resultado = "conta_criada"
    except AccountAlreadyExistsError:
        logger.warning(
            "Conta ja existia para este onboarding ao processar evento (idempotencia por onboarding_id).",
            extra={"context": {"onboarding_id": str(onboarding_id), "event_id": event_id}},
        )
        resultado = "conta_ja_existia"

    processed_event_repository.mark_processed(db, event_id, envelope.get("event_type", ""))
    db.commit()

    return resultado
