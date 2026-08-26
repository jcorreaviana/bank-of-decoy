"""Criptografia simetrica para dados sensiveis em repouso (specs/business/10-criptografia-cpf.md).

Mesma chave (`CPF_ENCRYPTION_KEY`) e mesmo esquema (Fernet) do
onboarding-service - necessario para decifrar o `cpf` recebido do
endpoint interno `GET /v1/onboarding/{id}/internal` e regrava-lo
criptografado em `accounts.cpf`. Ver app/core/crypto.py no
onboarding-service para o `cpf_hash` (blind index) - `accounts.cpf` nao
tem exigencia de unicidade (ver specs/business/02-modelo-dados.md), entao
esse servico so precisa cifrar/decifrar, sem indice determinístico.
"""

import os

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


def _get_key() -> bytes:
    key = os.environ.get("CPF_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("CPF_ENCRYPTION_KEY nao configurada.")
    return key.encode("utf-8")


def encrypt_value(plaintext: str) -> str:
    fernet = Fernet(_get_key())
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(ciphertext: str) -> str:
    fernet = Fernet(_get_key())
    try:
        return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Nao foi possivel decifrar o valor - chave incorreta ou dado corrompido.") from exc


class EncryptedString(TypeDecorator):
    """Coluna de texto criptografada em repouso, transparente para o ORM:
    o objeto Python sempre ve/atribui o valor em texto puro; o ciphertext
    e o que fica persistido no banco."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return encrypt_value(value)

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return decrypt_value(value)
