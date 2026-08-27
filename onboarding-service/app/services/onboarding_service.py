import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.crypto import compute_blind_index
from app.core.errors import CpfAlreadyRegisteredError, OnboardingNotFoundError
from app.core.logging import get_logger
from app.models import Onboarding
from app.repositories import onboarding_repository
from app.schemas.onboarding import OnboardingCreateRequest
from app.services.onboarding_events import publish_onboarding_classified
from app.services.onboarding_risk import evaluate_onboarding_risk

logger = get_logger(__name__)


@dataclass(frozen=True)
class OnboardingCreated:
    """Retrato do onboarding no momento da criacao (POST).

    O `status` aqui e sempre "em_analise": a classificacao de risco roda
    logo em seguida, dentro do mesmo request (ver specs/business/04-onboarding-risco.md),
    mas o contrato do POST sempre reflete o estado inicial - quem expoe o
    resultado final e o GET /v1/onboarding/{id}.
    """

    id: uuid.UUID
    status: str
    created_at: datetime


def create_onboarding(db: Session, payload: OnboardingCreateRequest) -> OnboardingCreated:
    existing = onboarding_repository.get_by_cpf_active(db, payload.cpf)
    if existing is not None:
        logger.warning(
            "Tentativa de onboarding com CPF ja registrado.",
            extra={"context": {"existing_onboarding_id": str(existing.id)}},
        )
        raise CpfAlreadyRegisteredError()

    onboarding = Onboarding(
        cpf=payload.cpf,
        cpf_hash=compute_blind_index(payload.cpf),
        nome=payload.nome,
        data_nascimento=payload.data_nascimento,
        email=payload.email,
        telefone=payload.telefone,
        documento_tipo=payload.documento_tipo,
        documento_numero=payload.documento_numero,
        dispositivo_id=payload.dispositivo_id,
        ip_origem=payload.ip_origem,
        status="em_analise",
    )
    try:
        onboarding = onboarding_repository.create(db, onboarding)
    except IntegrityError as exc:
        db.rollback()
        raise CpfAlreadyRegisteredError() from exc

    created = OnboardingCreated(id=onboarding.id, status=onboarding.status, created_at=onboarding.created_at)

    logger.info(
        "Onboarding criado.",
        extra={"context": {"onboarding_id": str(onboarding.id)}},
    )

    risk = evaluate_onboarding_risk(db, payload, exclude_id=onboarding.id)
    onboarding.status = risk.status
    onboarding.motivo_reprovacao = risk.motivo_reprovacao
    onboarding.risco_score = risk.score
    onboarding.risco_sinais = risk.sinais
    db.commit()

    logger.info(
        "Onboarding classificado.",
        extra={
            "context": {
                "onboarding_id": str(onboarding.id),
                "status": risk.status,
                "risco_score": risk.score,
            }
        },
    )

    # Sempre apos o commit acima (specs/tech/messaging.md) - o status
    # classificado ja esta persistido antes de qualquer evento sair.
    publish_onboarding_classified(db, onboarding)

    return created


def get_onboarding(db: Session, onboarding_id: uuid.UUID) -> Onboarding:
    onboarding = onboarding_repository.get_by_id_active(db, onboarding_id)
    if onboarding is None:
        raise OnboardingNotFoundError()
    return onboarding
