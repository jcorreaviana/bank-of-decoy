from app.models import Transaction
from sqlalchemy.orm import Session


def create(db: Session, transaction: Transaction) -> Transaction:
    db.add(transaction)
    db.flush()
    db.refresh(transaction)
    return transaction
