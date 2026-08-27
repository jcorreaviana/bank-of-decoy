import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.account import AccountCreateRequest, AccountCreateResponse, AccountDetailResponse
from app.services.account_service import create_account, get_account

router = APIRouter(prefix="/v1/accounts", tags=["accounts"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AccountCreateResponse)
def post_account(payload: AccountCreateRequest, db: Session = Depends(get_db)) -> AccountCreateResponse:
    """Rota OPERACIONAL de reprocessamento manual - desde a issue #7, o
    funil principal cria a conta automaticamente ao consumir o evento
    Kafka `onboarding.aprovado` (ver app/services/onboarding_event_consumer.py).
    Esta rota so deve ser usada para reprocessar manualmente um onboarding
    aprovado cujo evento tenha se perdido/corrompido - ela repete a mesma
    checagem de aprovacao do onboarding (ver docstring de `create_account`),
    nunca cria conta sem confirmar `status == "aprovado"`."""
    account = create_account(db, payload)
    return AccountCreateResponse(id=account.id, status=account.status, created_at=account.created_at)


@router.get("/{account_id}", response_model=AccountDetailResponse)
def get_account_detail(account_id: uuid.UUID, db: Session = Depends(get_db)) -> AccountDetailResponse:
    """Consulta minima de status, sem PII (sem `cpf`) - consumida hoje pelo
    transaction-service para validar `ACCOUNT_NOT_ACTIVE` antes de criar uma
    transacao (specs/business/06-pixkey-transaction-crud.md), na mesma
    filosofia sincrona/provisoria de 05-account-post-sincrono.md."""
    account = get_account(db, account_id)
    return AccountDetailResponse(
        id=account.id, status=account.status, tipo_conta=account.tipo_conta, created_at=account.created_at
    )
