import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PixKey


def get_by_valor_active(db: Session, valor: str) -> PixKey | None:
    stmt = select(PixKey).where(PixKey.valor == valor, PixKey.deleted_at.is_(None))
    return db.scalar(stmt)


def get_by_id_active(db: Session, pix_key_id: uuid.UUID) -> PixKey | None:
    stmt = select(PixKey).where(PixKey.id == pix_key_id, PixKey.deleted_at.is_(None))
    return db.scalar(stmt)


def create(db: Session, pix_key: PixKey) -> PixKey:
    db.add(pix_key)
    db.flush()
    db.refresh(pix_key)
    return pix_key


def soft_delete(db: Session, pix_key: PixKey) -> None:
    pix_key.deleted_at = datetime.now(timezone.utc)
    db.flush()
