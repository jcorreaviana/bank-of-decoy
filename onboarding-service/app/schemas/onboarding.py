import re
import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr, field_validator

_CPF_PATTERN = re.compile(r"^\d{11}$")


class OnboardingCreateRequest(BaseModel):
    cpf: str
    nome: str
    data_nascimento: date
    email: EmailStr
    telefone: str
    documento_tipo: str
    documento_numero: str
    dispositivo_id: str
    ip_origem: str

    @field_validator("cpf")
    @classmethod
    def validate_cpf(cls, value: str) -> str:
        if not _CPF_PATTERN.fullmatch(value):
            raise ValueError("cpf deve conter exatamente 11 digitos numericos")
        return value


class OnboardingCreateResponse(BaseModel):
    id: uuid.UUID
    status: str
    created_at: datetime


class RiscoCadastro(BaseModel):
    score: float | None = None
    sinais: list[str] = []


class OnboardingDetailResponse(BaseModel):
    id: uuid.UUID
    status: str
    risco_cadastro: RiscoCadastro
    created_at: datetime


class OnboardingInternalResponse(BaseModel):
    """Uso exclusivo servico-a-servico (ver GET /v1/onboarding/{id}/internal)."""

    id: uuid.UUID
    cpf: str
    status: str
    risco_cadastro: RiscoCadastro
    created_at: datetime
