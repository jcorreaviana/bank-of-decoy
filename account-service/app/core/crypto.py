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
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


def _get_key() -> bytes:
    key = os.environ.get("CPF_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("CPF_ENCRYPTION_KEY nao configurada.")
    return key.encode("utf-8")


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """Instancia o cipher uma unica vez e reaproveita entre chamadas -
    construir `Fernet(...)` a partir da chave base64 tem custo mensuravel
    (decode + setup de AES/HMAC), e `EncryptedString` chama
    encrypt_value/decrypt_value a cada linha lida/escrita da tabela
    `accounts` (toda leitura de conta decifra `cpf`, mesmo quando a
    resposta nao usa o campo, ex. `GET /v1/accounts/{id}` e
    `transferir_saldo`) - recriar o cipher por chamada era a causa raiz do
    p95 de latencia elevado detectado no account-service (issue #36),
    ajuste puramente operacional, sem mudanca de comportamento observavel."""
    return Fernet(_get_key())


def encrypt_value(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
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
