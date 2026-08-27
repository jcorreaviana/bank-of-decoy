import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import PixKeyAlreadyRegisteredError, PixKeyNotFoundError
from app.core.logging import get_logger
from app.models import PixKey
from app.repositories import pix_key_repository
from app.schemas.pix_key import PixKeyCreateRequest

logger = get_logger(__name__)


def create_pix_key(db: Session, payload: PixKeyCreateRequest) -> PixKey:
    existing = pix_key_repository.get_by_valor_active(db, payload.valor)
    if existing is not None:
        logger.warning(
            "Tentativa de registrar chave PIX ja registrada.",
            extra={"context": {"existing_pix_key_id": str(existing.id)}},
        )
        raise PixKeyAlreadyRegisteredError()

    pix_key = PixKey(account_id=payload.account_id, tipo=payload.tipo, valor=payload.valor)
    try:
        pix_key = pix_key_repository.create(db, pix_key)
    except IntegrityError as exc:
        db.rollback()
        raise PixKeyAlreadyRegisteredError() from exc

    db.commit()

    logger.info(
        "Chave PIX criada.",
        extra={"context": {"pix_key_id": str(pix_key.id), "account_id": str(payload.account_id)}},
    )

    return pix_key


def lookup_pix_key_by_valor(db: Session, valor: str) -> PixKey:
    pix_key = pix_key_repository.get_by_valor_any(db, valor)
    if pix_key is None:
        raise PixKeyNotFoundError()
    return pix_key


def delete_pix_key(db: Session, pix_key_id: uuid.UUID) -> None:
    pix_key = pix_key_repository.get_by_id_active(db, pix_key_id)
    if pix_key is None:
        raise PixKeyNotFoundError()

    pix_key_repository.soft_delete(db, pix_key)
    db.commit()

    logger.info("Chave PIX removida (soft delete).", extra={"context": {"pix_key_id": str(pix_key_id)}})
