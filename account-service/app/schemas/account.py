import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator


class AccountCreateRequest(BaseModel):
    onboarding_id: uuid.UUID
    tipo_conta: Literal["corrente", "poupanca"]


class AccountCreateResponse(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime


class AccountDetailResponse(BaseModel):
    id: uuid.UUID
    status: str
    tipo_conta: str
    created_at: datetime


class TransferenciaRequest(BaseModel):
    conta_origem_id: uuid.UUID
    conta_destino_id: uuid.UUID
    valor: float

    @field_validator("valor")
    @classmethod
    def validate_valor(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("valor deve ser maior que zero")
        return value


class TransferenciaResponse(BaseModel):
    conta_origem_id: uuid.UUID
    conta_destino_id: uuid.UUID
    saldo_origem: float
    saldo_destino: float
