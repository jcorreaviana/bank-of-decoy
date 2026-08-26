from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AccountAlreadyExistsError, OnboardingNotApprovedError, OnboardingNotFoundError
from app.core.logging import get_logger, get_trace_id
from app.models import Account
from app.repositories import account_repository
from app.schemas.account import AccountCreateRequest
from app.services.onboarding_internal_client import (
    OnboardingNotFoundUpstreamError,
    fetch_onboarding_internal,
)

logger = get_logger(__name__)


def create_account(db: Session, payload: AccountCreateRequest) -> Account:
    existing = account_repository.get_by_onboarding_id_active(db, payload.onboarding_id)
    if existing is not None:
        logger.warning(
            "Tentativa de criar conta para onboarding ja convertido.",
            extra={
                "context": {
                    "onboarding_id": str(payload.onboarding_id),
                    "existing_account_id": str(existing.id),
                }
            },
        )
        raise AccountAlreadyExistsError()

    logger.info(
        "Consultando onboarding-service (chamada sincrona) para criacao de conta.",
        extra={"context": {"onboarding_id": str(payload.onboarding_id)}},
    )
    try:
        onboarding = fetch_onboarding_internal(str(payload.onboarding_id), trace_id=get_trace_id())
    except OnboardingNotFoundUpstreamError:
        logger.warning(
            "Onboarding nao encontrado ao tentar criar conta.",
            extra={"context": {"onboarding_id": str(payload.onboarding_id)}},
        )
        raise OnboardingNotFoundError()

    if onboarding["status"] != "aprovado":
        logger.warning(
            "Tentativa de criar conta para onboarding nao aprovado.",
            extra={
                "context": {
                    "onboarding_id": str(payload.onboarding_id),
                    "onboarding_status": onboarding["status"],
                }
            },
        )
        raise OnboardingNotApprovedError()

    risco_cadastro = onboarding.get("risco_cadastro") or {}
    account = Account(
        onboarding_id=payload.onboarding_id,
        cpf=onboarding["cpf"],
        tipo_conta=payload.tipo_conta,
        status="ativa",
        risco_score=risco_cadastro.get("score"),
        risco_sinais=risco_cadastro.get("sinais") or [],
    )
    try:
        account = account_repository.create(db, account)
    except IntegrityError as exc:
        db.rollback()
        raise AccountAlreadyExistsError() from exc

    db.commit()

    logger.info(
        "Conta criada.",
        extra={"context": {"account_id": str(account.id), "onboarding_id": str(payload.onboarding_id)}},
    )

    return account
