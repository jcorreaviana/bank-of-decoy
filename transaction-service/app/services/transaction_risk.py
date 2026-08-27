"""Adaptador do transaction-service para o motor de risco compartilhado
(specs/business/06-pixkey-transaction-crud.md).

A regra de negocio em si (pesos, limiar, combinacao de sinais) foi
extraida para o pacote `risk_engine` (shared/risk_engine, issue #8),
compartilhado com o populador de volume. Este modulo cuida so da parte que
o pacote compartilhado deliberadamente nao faz: consultar o HISTORICO no
banco para os dois sinais que dependem dele (destinatario novo, velocidade
alta) e traduzir o payload Pydantic para o dataclass de input do motor.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from risk_engine.transaction import RiskResult, TransactionRiskInput, evaluate_transaction_risk as _evaluate_risk

from app.models import Transaction
from app.schemas.transaction import TransactionCreateRequest

__all__ = ["RiskResult", "check_destinatario_novo", "check_velocidade_alta", "evaluate_transaction_risk"]

JANELA_VELOCIDADE_ALTA = timedelta(minutes=10)
LIMIAR_VELOCIDADE_ALTA = 3  # transacoes anteriores na janela para considerar velocidade alta


def check_destinatario_novo(
    db: Session, account_id: uuid.UUID, pix_key_destino: str, exclude_id: uuid.UUID | None = None
) -> bool:
    """Simulado: primeira transacao dessa conta para esse pix_key_destino."""
    stmt = select(Transaction.id).where(
        Transaction.account_id == account_id,
        Transaction.pix_key_destino == pix_key_destino,
        Transaction.deleted_at.is_(None),
    )
    if exclude_id is not None:
        stmt = stmt.where(Transaction.id != exclude_id)
    return db.scalar(stmt.limit(1)) is None


def check_velocidade_alta(
    db: Session, account_id: uuid.UUID, agora: datetime, exclude_id: uuid.UUID | None = None
) -> bool:
    """Simulado: varias transacoes da mesma conta em janela curta."""
    janela_inicio = agora - JANELA_VELOCIDADE_ALTA
    stmt = select(func.count()).select_from(Transaction).where(
        Transaction.account_id == account_id,
        Transaction.created_at >= janela_inicio,
        Transaction.deleted_at.is_(None),
    )
    if exclude_id is not None:
        stmt = stmt.where(Transaction.id != exclude_id)
    count = db.scalar(stmt) or 0
    return count >= LIMIAR_VELOCIDADE_ALTA


def evaluate_transaction_risk(
    db: Session,
    payload: TransactionCreateRequest,
    account_id: uuid.UUID,
    agora: datetime | None = None,
    exclude_id: uuid.UUID | None = None,
) -> RiskResult:
    referencia = agora or datetime.now(timezone.utc)
    risk_input = TransactionRiskInput(
        valor=payload.valor,
        hora=referencia.hour,
        destinatario_novo=check_destinatario_novo(db, account_id, payload.pix_key_destino, exclude_id=exclude_id),
        velocidade_alta=check_velocidade_alta(db, account_id, referencia, exclude_id=exclude_id),
    )
    return _evaluate_risk(risk_input)
