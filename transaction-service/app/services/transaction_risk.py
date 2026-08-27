"""Gerador de risco da transacao (specs/business/06-pixkey-transaction-crud.md).

Mesma filosofia de app/services/onboarding_risk.py do onboarding-service:
regras deterministicas e simuladas, nao ML. A spec deixa em aberto como
"a combinacao de sinais determina risco_score" e trata "status: suspeita"
como derivado dessa combinacao - aqui, cada sinal contribui um peso e a
soma cruzando um limiar decide o status (mesmo padrao de soma+limiar usado
em onboarding_risk.py para reprovado_qualidade), o que evita marcar toda
transacao para um destinatario novo como suspeita isoladamente.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Transaction
from app.schemas.transaction import TransactionCreateRequest

PESO_VALOR_ATIPICO = 40
PESO_HORARIO_ATIPICO = 25
PESO_DESTINATARIO_NOVO = 20
PESO_VELOCIDADE_ALTA = 35
LIMIAR_SUSPEITA = 50

VALOR_ATIPICO_LIMIAR = 20_000.0
HORAS_ATIPICAS = frozenset({3})  # madrugada, 3h-4h
JANELA_VELOCIDADE_ALTA = timedelta(minutes=10)
LIMIAR_VELOCIDADE_ALTA = 3  # transacoes anteriores na janela para considerar velocidade alta


@dataclass(frozen=True)
class RiskResult:
    status: str
    score: float
    sinais: list[str]


def check_valor_atipico(payload: TransactionCreateRequest) -> bool:
    return payload.valor > VALOR_ATIPICO_LIMIAR


def check_horario_atipico(agora: datetime) -> bool:
    return agora.hour in HORAS_ATIPICAS


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

    sinais: list[str] = []
    score = 0.0

    if check_valor_atipico(payload):
        sinais.append("valor_atipico")
        score += PESO_VALOR_ATIPICO
    if check_horario_atipico(referencia):
        sinais.append("horario_atipico")
        score += PESO_HORARIO_ATIPICO
    if check_destinatario_novo(db, account_id, payload.pix_key_destino, exclude_id=exclude_id):
        sinais.append("destinatario_novo")
        score += PESO_DESTINATARIO_NOVO
    if check_velocidade_alta(db, account_id, referencia, exclude_id=exclude_id):
        sinais.append("velocidade_alta")
        score += PESO_VELOCIDADE_ALTA

    status = "suspeita" if score >= LIMIAR_SUSPEITA else "concluida"
    return RiskResult(status=status, score=score, sinais=sinais)
