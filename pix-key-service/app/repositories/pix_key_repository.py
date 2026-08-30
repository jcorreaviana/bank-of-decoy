import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PixKey


def get_by_valor_active(db: Session, valor: str) -> PixKey | None:
    stmt = select(PixKey).where(PixKey.valor == valor, PixKey.deleted_at.is_(None))
    return db.scalar(stmt)


def get_by_valor_any(db: Session, valor: str) -> PixKey | None:
    """Inclui chaves soft-deleted - usado pelo lookup de transaction-service,
    que precisa distinguir 'nunca existiu' (404) de 'existiu e foi cancelada'
    (422), não só 'existe e está ativa' (specs/business/15-validacao-chave-destino.md).
    Quando há mais de um registro para o mesmo `valor` (histórico de cancelar
    e recriar), pega o mais recente.

    Causa raiz do sinal `latencia_alta` (issue #71): esta query não filtrava
    `deleted_at`, então nunca conseguia usar o índice único parcial
    `ix_pix_keys_valor_unique_not_deleted` (que só cobre `deleted_at IS NULL`)
    - todo lookup, mesmo para o caso comum de chave ativa, forçava um scan
    completo da tabela ordenado por `created_at`. Como esse endpoint
    (`GET /v1/pix-keys/lookup`) é chamado a cada transação por
    transaction-service, o custo aparecia direto no p95 do serviço.
    Correção: tenta primeiro a chave ativa via `get_by_valor_active` (usa o
    índice parcial, caminho rápido e mais comum) e só cai para o scan
    completo do histórico quando não há chave ativa - uma chave ativa para
    um `valor`, quando existe, é sempre a mais recente (o índice único
    parcial garante que só existe uma por vez, e reaproveitar um `valor` exige
    soft-deletar a anterior antes), então o resultado retornado é idêntico ao
    da query anterior."""
    active = get_by_valor_active(db, valor)
    if active is not None:
        return active

    stmt = select(PixKey).where(PixKey.valor == valor).order_by(PixKey.created_at.desc())
    return db.scalars(stmt).first()


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
