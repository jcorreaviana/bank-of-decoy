from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.account import AccountCreateRequest, AccountCreateResponse
from app.services.account_service import create_account

router = APIRouter(prefix="/v1/accounts", tags=["accounts"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AccountCreateResponse)
def post_account(payload: AccountCreateRequest, db: Session = Depends(get_db)) -> AccountCreateResponse:
    account = create_account(db, payload)
    return AccountCreateResponse(id=account.id, status=account.status, created_at=account.created_at)
