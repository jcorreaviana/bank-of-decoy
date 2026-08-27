from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.transaction import RiscoTransacao, TransactionCreateRequest, TransactionCreateResponse
from app.services.transaction_service import create_transaction

router = APIRouter(prefix="/v1/transactions", tags=["transactions"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TransactionCreateResponse)
def post_transaction(payload: TransactionCreateRequest, db: Session = Depends(get_db)) -> TransactionCreateResponse:
    transaction = create_transaction(db, payload)
    return TransactionCreateResponse(
        id=transaction.id,
        e2e_id=transaction.e2e_id,
        status=transaction.status,
        risco_transacao=RiscoTransacao(score=transaction.risco_score, sinais=transaction.risco_sinais or []),
        created_at=transaction.created_at,
    )
