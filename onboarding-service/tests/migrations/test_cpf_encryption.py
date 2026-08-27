import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from test_safety import require_disposable_database

from app.core.config import get_settings
from app.core.crypto import compute_blind_index, decrypt_value
from app.main import app

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.database_url or not os.environ.get("CPF_ENCRYPTION_KEY"),
    reason="DATABASE_URL/CPF_ENCRYPTION_KEY nao configuradas - teste de criptografia requer banco real.",
)


@pytest.fixture(autouse=True)
def _clean_onboardings_table():
    require_disposable_database(settings.database_url)
    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE onboardings"))
    yield
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE onboardings"))


def test_cpf_nao_aparece_em_texto_puro_consultando_o_banco_diretamente() -> None:
    client = TestClient(app)
    cpf = "64720340009"

    created = client.post(
        "/v1/onboarding",
        json={
            "cpf": cpf,
            "nome": "Confidencial Silva",
            "data_nascimento": "1990-05-20",
            "email": "confidencial@example.com",
            "telefone": "11999999999",
            "documento_tipo": "rg",
            "documento_numero": "1234567",
            "dispositivo_id": "device-crypto-test",
            "ip_origem": "203.0.113.10",
        },
    ).json()

    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT cpf, cpf_hash FROM onboardings WHERE id = :id"), {"id": created["id"]}
        ).one()

    raw_cpf_column = row.cpf
    raw_cpf_hash_column = row.cpf_hash

    # a consulta direta (fora da aplicacao) nunca expoe o CPF em texto puro
    assert raw_cpf_column != cpf
    assert cpf not in raw_cpf_column

    # mas o dado e recuperavel pela aplicacao, com a chave correta
    assert decrypt_value(raw_cpf_column) == cpf

    # e o indice de unicidade (cpf_hash) bate com o HMAC deterministico do CPF
    assert raw_cpf_hash_column == compute_blind_index(cpf)
