import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import CpfAlreadyRegisteredError, OnboardingNotFoundError
from app.core.logging import get_logger
from app.models import Onboarding
from app.repositories import onboarding_repository
from app.schemas.onboarding import OnboardingCreateRequest

logger = get_logger(__name__)


def create_onboarding(db: Session, payload: OnboardingCreateRequest) -> Onboarding:
    existing = onboarding_repository.get_by_cpf_active(db, payload.cpf)
    if existing is not None:
        logger.warning(
            "Tentativa de onboarding com CPF ja registrado.",
            extra={"context": {"existing_onboarding_id": str(existing.id)}},
        )
        raise CpfAlreadyRegisteredError()

    onboarding = Onboarding(
        cpf=payload.cpf,
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

    logger.info(
        "Onboarding criado.",
        extra={"context": {"onboarding_id": str(onboarding.id)}},
    )
    return onboarding


def get_onboarding(db: Session, onboarding_id: uuid.UUID) -> Onboarding:
    onboarding = onboarding_repository.get_by_id_active(db, onboarding_id)
    if onboarding is None:
        raise OnboardingNotFoundError()
    return onboarding
