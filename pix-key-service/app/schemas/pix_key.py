import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ValidationInfo, field_validator

_CPF_PATTERN = re.compile(r"^\d{11}$")
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TELEFONE_PATTERN = re.compile(r"^\d{10,11}$")


class PixKeyCreateRequest(BaseModel):
    account_id: uuid.UUID
    tipo: Literal["cpf", "email", "telefone", "aleatoria"]
    valor: str

    @field_validator("valor")
    @classmethod
    def validate_valor(cls, value: str, info: ValidationInfo) -> str:
        tipo = info.data.get("tipo")
        valor = value.strip()
        if not valor:
            raise ValueError("valor nao pode ser vazio")
        if tipo == "cpf" and not _CPF_PATTERN.fullmatch(valor):
            raise ValueError("valor deve conter exatamente 11 digitos numericos para tipo cpf")
        if tipo == "email" and not _EMAIL_PATTERN.fullmatch(valor):
            raise ValueError("valor deve ser um email valido para tipo email")
        if tipo == "telefone" and not _TELEFONE_PATTERN.fullmatch(valor):
            raise ValueError("valor deve conter 10 ou 11 digitos numericos para tipo telefone")
        return value


class PixKeyCreateResponse(BaseModel):
    id: uuid.UUID
    tipo: str
    valor: str
    created_at: datetime
