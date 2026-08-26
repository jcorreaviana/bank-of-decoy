import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Onboarding


def get_by_cpf_active(db: Session, cpf: str) -> Onboarding | None:
    stmt = select(Onboarding).where(Onboarding.cpf == cpf, Onboarding.deleted_at.is_(None))
    return db.scalar(stmt)


def get_by_id_active(db: Session, onboarding_id: uuid.UUID) -> Onboarding | None:
    stmt = select(Onboarding).where(Onboarding.id == onboarding_id, Onboarding.deleted_at.is_(None))
    return db.scalar(stmt)


def create(db: Session, onboarding: Onboarding) -> Onboarding:
    db.add(onboarding)
    db.flush()
    db.refresh(onboarding)
    return onboarding
