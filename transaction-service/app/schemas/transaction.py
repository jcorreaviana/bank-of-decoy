import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator


class TransactionCreateRequest(BaseModel):
    account_id: uuid.UUID
    pix_key_destino: str
    valor: float

    @field_validator("pix_key_destino")
    @classmethod
    def validate_pix_key_destino(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("pix_key_destino nao pode ser vazio")
        return value

    @field_validator("valor")
    @classmethod
    def validate_valor(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("valor deve ser maior que zero")
        return value


class RiscoTransacao(BaseModel):
    score: float
    sinais: list[str]


class TransactionCreateResponse(BaseModel):
    id: uuid.UUID
    status: str
    risco_transacao: RiscoTransacao
    created_at: datetime
