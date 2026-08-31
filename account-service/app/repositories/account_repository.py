import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from app.models import Account

# `cpf` e EncryptedString (app/core/crypto.py): toda linha carregada com essa
# coluna paga o custo de decifrar (Fernet/AES), mesmo quando o chamador nunca
# usa o valor - causa raiz do sinal `latencia_alta` do account-service (issue
# #70) nos dois endpoints HTTP mais quentes (GET /v1/accounts/{id} e POST
# /v1/accounts/transferencias, chamados a cada transacao). `defer()` evita
# carregar/decifrar a coluna quando ela nao e necessaria - ajuste puramente
# operacional, sem mudanca de comportamento observavel (quem precisa do cpf
# continua usando as queries sem defer, ex. create_account/create_account_from_event
# via get_by_onboarding_id_active nao le cpf hoje, so cria linha nova).


def get_by_onboarding_id_active(db: Session, onboarding_id: uuid.UUID) -> Account | None:
    stmt = (
        select(Account)
        .where(Account.onboarding_id == onboarding_id, Account.deleted_at.is_(None))
        .options(defer(Account.cpf))
    )
    return db.scalar(stmt)


def get_by_id_active(db: Session, account_id: uuid.UUID) -> Account | None:
    """Usado por `get_account` (GET /v1/accounts/{account_id}), cuja resposta
    (`AccountDetailResponse`) nunca inclui `cpf` (specs/business/05) - decifrar
    aqui era custo puro sem uso."""
    stmt = (
        select(Account)
        .where(Account.id == account_id, Account.deleted_at.is_(None))
        .options(defer(Account.cpf))
    )
    return db.scalar(stmt)


def get_by_id_active_for_update(db: Session, account_id: uuid.UUID) -> Account | None:
    """Mesma consulta de `get_by_id_active`, mas com `SELECT ... FOR UPDATE`
    - usado pela transferencia de saldo (specs/business/16-saldo-partida-dobrada.md)
    para travar a linha durante o debito/credito e evitar corrida entre
    duas transferencias concorrentes na mesma conta. `transferir_saldo` so
    le/escreve `saldo`, nunca `cpf` - mesmo racional de `defer()`."""
    stmt = (
        select(Account)
        .where(Account.id == account_id, Account.deleted_at.is_(None))
        .options(defer(Account.cpf))
        .with_for_update()
    )
    return db.scalar(stmt)


def create(db: Session, account: Account) -> Account:
    db.add(account)
    db.flush()
    db.refresh(account)
    return account
