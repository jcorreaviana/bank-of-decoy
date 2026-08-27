from app.models import Transaction
from sqlalchemy.orm import Session


def create(db: Session, transaction: Transaction) -> Transaction:
    db.add(transaction)
    db.flush()
    db.refresh(transaction)
    return transaction


def create_par(db: Session, saida: Transaction, entrada: Transaction) -> tuple[Transaction, Transaction]:
    """Cria as duas linhas da partida dobrada (specs/business/16-saldo-partida-dobrada.md)
    numa unica escrita - as duas ou nenhuma, nunca uma sem a outra."""
    db.add_all([saida, entrada])
    db.flush()
    db.refresh(saida)
    db.refresh(entrada)
    return saida, entrada
