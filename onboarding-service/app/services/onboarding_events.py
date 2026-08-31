"""Publicacao dos eventos de classificacao do onboarding
(specs/business/07-kafka-onboarding-eventos.md, specs/tech/messaging.md).

Um topico por resultado (`onboarding.aprovado`, `onboarding.reprovado_qualidade`,
`onboarding.reprovado_fraude`). `reprovado_qualidade`/`reprovado_fraude` sao
publicados TAMBEM na fila de revisao correspondente (`onboarding.revisao_qualidade`
/ `onboarding.revisao_compliance`) - o mesmo fato de negocio, mesmo `event_id`,
em dois topicos: o topico "de resultado" e o generico canal de auditoria/
outros consumidores futuros, a fila de revisao e o canal que uma futura
rotina de revisao manual vai consumir (issue #7 so cria o topico e publica
o evento - a logica de retentativa em si, alem do utilitario testavel em
app/services/review_retry.py, fica para uma proxima issue).

Decisao de payload (confirmada com o autor da issue, diverge do texto
literal da spec 07 que so previa `onboarding_id`/`motivo_reprovacao`): o
evento `onboarding.aprovado` carrega `cpf` CIFRADO (mesmo ciphertext
Fernet da coluna `onboardings.cpf`, nunca decifrado aqui) + `risco_score` +
`risco_sinais`, para o account-service criar a conta sem nenhuma chamada
sincrona de volta ao onboarding-service. "payload nao contem CPF" (security.md)
e interpretado como "nao em texto claro" - mesma logica ja aplicada ao
endpoint GET /v1/onboarding/{id}/internal (issue #3/#10).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.kafka import publish_events
from app.core.logging import get_trace_id
from app.models import Onboarding
from app.repositories import onboarding_repository

_TOPICOS_RESULTADO = {
    "aprovado": "onboarding.aprovado",
    "reprovado_qualidade": "onboarding.reprovado_qualidade",
    "reprovado_fraude": "onboarding.reprovado_fraude",
}

_TOPICOS_REVISAO = {
    "reprovado_qualidade": "onboarding.revisao_qualidade",
    "reprovado_fraude": "onboarding.revisao_compliance",
}


def _iso8601_utc(dt: datetime) -> str:
    dt_utc = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt_utc.microsecond // 1000:03d}Z"


def _build_payload(db: Session, onboarding: Onboarding) -> dict:
    payload: dict = {
        "onboarding_id": str(onboarding.id),
        "risco_score": float(onboarding.risco_score) if onboarding.risco_score is not None else None,
        "risco_sinais": list(onboarding.risco_sinais or []),
    }
    if onboarding.status == "aprovado":
        payload["cpf"] = onboarding_repository.get_raw_cpf_ciphertext(db, onboarding.id)
    else:
        payload["motivo_reprovacao"] = onboarding.motivo_reprovacao
    return payload


def _build_envelope(event_type: str, onboarding: Onboarding, payload: dict) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": _iso8601_utc(onboarding.updated_at),
        "trace_id": get_trace_id(),
        "payload": payload,
    }


def publish_onboarding_classified(db: Session, onboarding: Onboarding) -> None:
    """Chamar SEMPRE depois do `db.commit()` que persistiu `onboarding.status`
    (specs/tech/messaging.md: "publicacao ocorre apos commit da transacao,
    nunca antes") - nunca antes, senao publicariamos um fato que pode nao
    ter sido persistido (rollback)."""
    topico_resultado = _TOPICOS_RESULTADO.get(onboarding.status)
    if topico_resultado is None:
        return

    payload = _build_payload(db, onboarding)
    envelope = _build_envelope(topico_resultado, onboarding, payload)

    key = str(onboarding.id)
    eventos: list[tuple[str, dict, str | None]] = [(topico_resultado, envelope, key)]

    topico_revisao = _TOPICOS_REVISAO.get(onboarding.status)
    if topico_revisao is not None:
        eventos.append((topico_revisao, envelope, key))

    # Um unico flush para todos os eventos deste fato de negocio (issue #69)
    # - ver docstring de app/core/kafka.publish_events.
    publish_events(eventos)
