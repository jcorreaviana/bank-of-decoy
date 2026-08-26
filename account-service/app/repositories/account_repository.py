import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account


def get_by_onboarding_id_active(db: Session, onboarding_id: uuid.UUID) -> Account | None:
    stmt = select(Account).where(Account.onboarding_id == onboarding_id, Account.deleted_at.is_(None))
    return db.scalar(stmt)


def create(db: Session, account: Account) -> Account:
    db.add(account)
    db.flush()
    db.refresh(account)
    return account
