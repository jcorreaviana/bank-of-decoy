"""Criptografia simetrica para dados sensiveis em repouso (specs/business/10-criptografia-cpf.md).

Usa Fernet (AES-128-CBC + HMAC, com IV aleatorio por chamada) para o valor
recuperavel armazenado em `cpf`. Fernet e nao-deterministico por design -
o mesmo texto claro gera ciphertexts diferentes a cada chamada - entao ele
sozinho nao pode alimentar um indice de unicidade/lookup. Para isso existe
`compute_blind_index`: um HMAC-SHA256 deterministico e nao reversivel do
mesmo valor, usado apenas para comparacao de igualdade (ver `cpf_hash` em
app/models/onboarding.py).
"""

import base64
import hashlib
import hmac
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator


@lru_cache(maxsize=1)
def _get_key() -> bytes:
    key = os.environ.get("CPF_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("CPF_ENCRYPTION_KEY nao configurada.")
    return key.encode("utf-8")


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    # `CPF_ENCRYPTION_KEY` nao muda em runtime (fixture de teste que troca a
    # variavel de ambiente precisa chamar `_get_key.cache_clear()` e
    # `_get_fernet.cache_clear()`) - instanciar o Fernet uma unica vez evita
    # decodificar/validar a chave a cada chamada de encrypt/decrypt, custo
    # que se repete em toda requisicao de onboarding (issue #34: p95 de
    # latencia acima do esperado no onboarding-service).
    return Fernet(_get_key())


def encrypt_value(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Nao foi possivel decifrar o valor - chave incorreta ou dado corrompido.") from exc


def compute_blind_index(plaintext: str) -> str:
    """HMAC-SHA256 deterministico do valor - permite lookup/unicidade sem
    expor nem decifrar o dado (a saida nao e reversivel para o valor original)."""
    digest = hmac.new(_get_key(), plaintext.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8")


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
