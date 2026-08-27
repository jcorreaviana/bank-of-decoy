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

__all__ = [
    "RiskResult",
    "check_destinatario_novo",
    "check_velocidade_alta",
    "check_entrada_saida_rapida",
    "evaluate_transaction_risk",
]

JANELA_VELOCIDADE_ALTA = timedelta(minutes=10)
LIMIAR_VELOCIDADE_ALTA = 3  # transacoes anteriores na janela para considerar velocidade alta

JANELA_ENTRADA_SAIDA_RAPIDA = timedelta(minutes=10)  # mesma janela de velocidade_alta, por consistencia
RAZAO_ENTRADA_SAIDA_RAPIDA = 0.7  # 0.7 = 70% do valor da transacao de saida
"""Fracao minima do valor da saida atual que precisa ter chegado via
entrada recente para caracterizar passagem de mula (specs/business/16-saldo-partida-dobrada.md)
- 0.7 tolera uma pequena "sobra" retida na conta (comum em padroes reais de
lavagem, que raramente repassam 100% do valor recebido) sem deixar de
capturar o caso classico de passagem quase integral."""


def check_destinatario_novo(
    db: Session, account_id: uuid.UUID, pix_key_destino: str, exclude_id: uuid.UUID | None = None
) -> bool:
    """Simulado: primeira transacao dessa conta para esse pix_key_destino.
    Filtra `tipo == "saida"` (partida dobrada, issue #16) - uma linha
    `entrada` desta conta representa dinheiro RECEBIDO, nao um envio dela
    para o destino, entao nao conta como "ja enviou para esse destinatario"."""
    stmt = select(Transaction.id).where(
        Transaction.account_id == account_id,
        Transaction.tipo == "saida",
        Transaction.pix_key_destino == pix_key_destino,
        Transaction.deleted_at.is_(None),
    )
    if exclude_id is not None:
        stmt = stmt.where(Transaction.id != exclude_id)
    return db.scalar(stmt.limit(1)) is None


def check_velocidade_alta(
    db: Session, account_id: uuid.UUID, agora: datetime, exclude_id: uuid.UUID | None = None
) -> bool:
    """Simulado: varias transacoes ENVIADAS pela mesma conta em janela curta.
    Filtra `tipo == "saida"` (partida dobrada, issue #16) pelo mesmo motivo
    de `check_destinatario_novo` - contar entradas aqui misturaria "enviar
    rapido" com "receber rapido", que ja tem sinal proprio
    (`entrada_saida_rapida`)."""
    janela_inicio = agora - JANELA_VELOCIDADE_ALTA
    stmt = select(func.count()).select_from(Transaction).where(
        Transaction.account_id == account_id,
        Transaction.tipo == "saida",
        Transaction.created_at >= janela_inicio,
        Transaction.deleted_at.is_(None),
    )
    if exclude_id is not None:
        stmt = stmt.where(Transaction.id != exclude_id)
    count = db.scalar(stmt) or 0
    return count >= LIMIAR_VELOCIDADE_ALTA


def check_entrada_saida_rapida(db: Session, account_id: uuid.UUID, valor: float, agora: datetime) -> bool:
    """Simulado: a conta de origem recebeu uma entrada recente cujo valor
    cobre uma fracao significativa do que esta prestes a sair agora - padrao
    mula bidirecional, so detectavel com o ledger de partida dobrada (a
    entrada e uma linha `tipo='entrada'` com `account_id` = esta conta,
    escrita quando ELA foi destino de uma transferencia anterior)."""
    janela_inicio = agora - JANELA_ENTRADA_SAIDA_RAPIDA
    limiar_valor = valor * RAZAO_ENTRADA_SAIDA_RAPIDA
    stmt = select(Transaction.id).where(
        Transaction.account_id == account_id,
        Transaction.tipo == "entrada",
        Transaction.valor >= limiar_valor,
        Transaction.created_at >= janela_inicio,
        Transaction.deleted_at.is_(None),
    )
    return db.scalar(stmt.limit(1)) is not None


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
        entrada_saida_rapida=check_entrada_saida_rapida(db, account_id, payload.valor, referencia),
    )
    return _evaluate_risk(risk_input)
