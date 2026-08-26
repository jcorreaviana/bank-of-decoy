"""Prova de interoperabilidade da criptografia de CPF entre onboarding-service
e account-service (specs/business/10-criptografia-cpf.md).

Requer os dois servicos "reais": um onboarding-service acessivel em
ONBOARDING_SERVICE_URL (para criar o onboarding e servir o endpoint
interno) e um Postgres acessivel em DATABASE_URL (banco `account`) - sem
qualquer um dos dois, o teste e pulado. Nao reimplementa a orquestracao
de POST /v1/accounts (issue #5, ainda pausada): so valida que o
account-service consegue decifrar o que recebe e regravar criptografado.
"""

import os
import random
import uuid

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_value
from app.models import Account
from app.services.onboarding_internal_client import fetch_onboarding_internal

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.database_url or not os.environ.get("CPF_ENCRYPTION_KEY") or not settings.onboarding_service_url,
    reason=(
        "DATABASE_URL/CPF_ENCRYPTION_KEY/ONBOARDING_SERVICE_URL nao configuradas - "
        "teste de interoperabilidade requer onboarding-service e Postgres reais."
    ),
)


@pytest.fixture(autouse=True)
def _clean_accounts_table():
    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE accounts"))
    yield
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE accounts"))


def _create_onboarding_via_http(cpf: str) -> str:
    # documento_numero/dispositivo_id/ip_origem tambem variam por execucao:
    # o gerador de risco do onboarding-service (issue #4) marca como
    # padrao_mula/documento_reciclado um IP, dispositivo ou documento
    # reaproveitado num onboarding recente - um valor fixo faria a segunda
    # execucao consecutiva deste teste virar reprovado_fraude.
    sufixo = uuid.uuid4().hex[:8]
    response = httpx.post(
        f"{settings.onboarding_service_url}/v1/onboarding",
        json={
            "cpf": cpf,
            "nome": "Interop Test",
            "data_nascimento": "1990-01-01",
            "email": "interop@example.com",
            "telefone": "11999999999",
            "documento_tipo": "rg",
            "documento_numero": f"IT{sufixo}",
            "dispositivo_id": f"device-interop-{sufixo}",
            "ip_origem": f"203.0.{random.randint(0, 255)}.{random.randint(0, 255)}",
        },
        timeout=5.0,
    )
    response.raise_for_status()
    return response.json()["id"]


def test_account_service_decrypts_internal_cpf_and_stores_it_encrypted() -> None:
    # CPF aleatorio a cada execucao: este teste cria um onboarding real via
    # HTTP no onboarding-service, cujo banco esta fora do controle da
    # fixture de limpeza deste arquivo (que so trunca `accounts`) - um
    # valor fixo colidiria com o indice unico de CPFs nao deletados em
    # reexecucoes.
    cpf = "".join(random.choices("0123456789", k=11))
    onboarding_id = _create_onboarding_via_http(cpf)

    payload = fetch_onboarding_internal(onboarding_id, trace_id=str(uuid.uuid4()))

    assert payload["cpf"] == cpf
    assert payload["status"] == "aprovado"

    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        account = Account(
            id=uuid.uuid4(),
            onboarding_id=uuid.UUID(onboarding_id),
            cpf=payload["cpf"],
            status="ativa",
            risco_score=payload["risco_cadastro"]["score"],
            risco_sinais=payload["risco_cadastro"]["sinais"],
        )
        session.add(account)
        session.flush()
        account_id = account.id

        raw_cpf = session.execute(
            text("SELECT cpf FROM accounts WHERE id = :id"), {"id": str(account_id)}
        ).scalar_one()

        # nunca em texto puro na consulta direta ao banco
        assert raw_cpf != cpf
        assert cpf not in raw_cpf
        # mas recuperavel pela aplicacao, com a mesma chave
        assert decrypt_value(raw_cpf) == cpf

        session.rollback()
