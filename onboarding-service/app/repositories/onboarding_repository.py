import uuid

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.crypto import compute_blind_index
from app.models import Onboarding


def get_by_cpf_active(db: Session, cpf: str) -> Onboarding | None:
    # `cpf` e criptografado de forma nao-deterministica (Fernet) - a busca
    # usa o `cpf_hash` (HMAC-SHA256 deterministico) em vez de comparar a
    # coluna criptografada diretamente. Ver app/core/crypto.py.
    stmt = select(Onboarding).where(
        Onboarding.cpf_hash == compute_blind_index(cpf), Onboarding.deleted_at.is_(None)
    )
    return db.scalar(stmt)


def get_raw_cpf_ciphertext(db: Session, onboarding_id: uuid.UUID) -> str | None:
    """Le o valor bruto (ciphertext) de `cpf` diretamente, sem passar pelo
    `EncryptedString` do model - usado pelo endpoint interno
    (GET /v1/onboarding/{id}/internal), que repassa o CPF ainda
    criptografado para o account-service sem decifrar nesta camada."""
    stmt = text("SELECT cpf FROM onboardings WHERE id = :id AND deleted_at IS NULL")
    result = db.execute(stmt, {"id": str(onboarding_id)})
    row = result.first()
    return row[0] if row is not None else None


def get_by_id_active(db: Session, onboarding_id: uuid.UUID) -> Onboarding | None:
    stmt = select(Onboarding).where(Onboarding.id == onboarding_id, Onboarding.deleted_at.is_(None))
    return db.scalar(stmt)


def create(db: Session, onboarding: Onboarding) -> Onboarding:
    db.add(onboarding)
    db.flush()
    db.refresh(onboarding)
    return onboarding
