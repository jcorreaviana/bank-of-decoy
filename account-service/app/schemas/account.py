import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class AccountCreateRequest(BaseModel):
    onboarding_id: uuid.UUID
    tipo_conta: Literal["corrente", "poupanca"]


class AccountCreateResponse(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime
