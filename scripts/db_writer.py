"""Escrita em lote direto no banco de cada servico (specs/business/08-populador-volume.md:
"popula diretamente via repository/banco quando o volume via HTTP for
inviavel" - 500k+ contas e ate ~25M transacoes tornam a API/Kafka
inviaveis em tempo de execucao).

Deliberadamente NAO importa `app.*` de nenhum servico: os quatro servicos
usam o mesmo nome de pacote top-level (`app`), o que colidiria se
importados no mesmo processo (ver stack.md - estrutura de pastas
identica por design). Em vez disso, reflete o schema real (`MetaData.reflect`)
para obter os `Table` a partir do banco ja migrado - o populador so roda
depois que `alembic upgrade head` ja rodou em cada servico (issue #2).

A cifragem de `cpf` (Fernet + blind index HMAC-SHA256) e reimplementada
aqui, identica a app/core/crypto.py de onboarding-service/account-service
(issue #10) - duplicacao pequena e deliberada, no mesmo espirito de cada
servico ja ter sua propria copia independente desse modulo (nenhum dos
dois importa do outro hoje)."""

import base64
import hashlib
import hmac
import os
from collections.abc import Iterable, Sequence

from cryptography.fernet import Fernet
from sqlalchemy import MetaData, Table, create_engine, insert
from sqlalchemy.engine import Engine

from generation import AccountRecord, OnboardingRecord, PixKeyRecord, TransactionRecord


def _get_cpf_key() -> bytes:
    key = os.environ.get("CPF_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("CPF_ENCRYPTION_KEY nao configurada.")
    return key.encode("utf-8")


def encrypt_cpf(plaintext: str) -> str:
    return Fernet(_get_cpf_key()).encrypt(plaintext.encode("utf-8")).decode("utf-8")


def compute_cpf_blind_index(plaintext: str) -> str:
    digest = hmac.new(_get_cpf_key(), plaintext.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8")


class ServiceDatabase:
    """Uma conexao + as Table refletidas de um banco de um servico."""

    def __init__(self, database_url: str, table_names: Sequence[str]) -> None:
        self.engine: Engine = create_engine(database_url, pool_pre_ping=True)
        metadata = MetaData()
        metadata.reflect(bind=self.engine, only=table_names)
        self.tables: dict[str, Table] = {name: metadata.tables[name] for name in table_names}

    def bulk_insert(self, table_name: str, rows: Sequence[dict]) -> None:
        if not rows:
            return
        table = self.tables[table_name]
        with self.engine.begin() as conn:
            conn.execute(insert(table), rows)

    def dispose(self) -> None:
        self.engine.dispose()


def onboarding_row(record: OnboardingRecord) -> dict:
    return {
        "id": record.id,
        "cpf": encrypt_cpf(record.cpf),
        "cpf_hash": compute_cpf_blind_index(record.cpf),
        "nome": record.nome,
        "data_nascimento": record.data_nascimento,
        "email": record.email,
        "telefone": record.telefone,
        "documento_tipo": record.documento_tipo,
        "documento_numero": record.documento_numero,
        "dispositivo_id": record.dispositivo_id,
        "ip_origem": record.ip_origem,
        "status": record.status,
        "motivo_reprovacao": record.motivo_reprovacao,
        "risco_score": record.risco_score,
        "risco_sinais": record.risco_sinais,
        "created_at": record.created_at,
        "updated_at": record.created_at,
    }


def account_row(record: AccountRecord) -> dict:
    return {
        "id": record.id,
        "onboarding_id": record.onboarding_id,
        "cpf": encrypt_cpf(record.cpf),
        "status": record.status,
        "tipo_conta": record.tipo_conta,
        "risco_score": record.risco_score,
        "risco_sinais": record.risco_sinais,
        "created_at": record.created_at,
        "updated_at": record.created_at,
    }


def pix_key_row(record: PixKeyRecord) -> dict:
    return {
        "id": record.id,
        "account_id": record.account_id,
        "tipo": record.tipo,
        "valor": record.valor,
        "created_at": record.created_at,
        "updated_at": record.created_at,
    }


def transaction_row(record: TransactionRecord) -> dict:
    return {
        "id": record.id,
        "account_id": record.account_id,
        "pix_key_destino": record.pix_key_destino,
        "valor": record.valor,
        "status": record.status,
        "risco_score": record.risco_score,
        "risco_sinais": record.risco_sinais,
        "original_transaction_id": None,
        "created_at": record.created_at,
        "updated_at": record.created_at,
    }


def chunked(iterable: Iterable, size: int):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
