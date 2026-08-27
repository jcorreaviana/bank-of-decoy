import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account


def get_by_onboarding_id_active(db: Session, onboarding_id: uuid.UUID) -> Account | None:
    stmt = select(Account).where(Account.onboarding_id == onboarding_id, Account.deleted_at.is_(None))
    return db.scalar(stmt)


def get_by_id_active(db: Session, account_id: uuid.UUID) -> Account | None:
    stmt = select(Account).where(Account.id == account_id, Account.deleted_at.is_(None))
    return db.scalar(stmt)


def get_by_id_active_for_update(db: Session, account_id: uuid.UUID) -> Account | None:
    """Mesma consulta de `get_by_id_active`, mas com `SELECT ... FOR UPDATE`
    - usado pela transferencia de saldo (specs/business/16-saldo-partida-dobrada.md)
    para travar a linha durante o debito/credito e evitar corrida entre
    duas transferencias concorrentes na mesma conta."""
    stmt = select(Account).where(Account.id == account_id, Account.deleted_at.is_(None)).with_for_update()
    return db.scalar(stmt)


def create(db: Session, account: Account) -> Account:
    db.add(account)
    db.flush()
    db.refresh(account)
    return account
