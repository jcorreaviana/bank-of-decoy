"""Testa a logica PURA de consumo do evento onboarding.aprovado
(process_onboarding_aprovado_envelope) contra um banco real, sem precisar
de um broker Kafka de verdade - o "consumo" aqui e so chamar a funcao com
um envelope sintetico, a mesma tecnica ja usada para dublar o
onboarding-service em test_account.py (issue #5)."""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from test_safety import require_disposable_database

from app.core.config import get_settings
from app.core.crypto import encrypt_value
from app.services.onboarding_event_consumer import process_onboarding_aprovado_envelope

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.database_url or not os.environ.get("CPF_ENCRYPTION_KEY"),
    reason="DATABASE_URL/CPF_ENCRYPTION_KEY nao configuradas - teste requer banco real.",
)


@pytest.fixture(autouse=True)
def _clean_tables():
    require_disposable_database(settings.database_url)
    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE accounts, processed_events"))
    yield
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE accounts, processed_events"))


def _session():
    engine = create_engine(settings.database_url)
    session_factory = sessionmaker(bind=engine)
    return session_factory()


def _envelope(onboarding_id: str | None = None, **payload_overrides) -> dict:
    payload = {
        "onboarding_id": onboarding_id or str(uuid.uuid4()),
        "cpf": encrypt_value("12345678901"),
        "risco_score": 10.0,
        "risco_sinais": ["dados_inconsistentes"],
    }
    payload.update(payload_overrides)
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": "onboarding.aprovado",
        "occurred_at": "2026-01-01T00:00:00.000Z",
        "trace_id": "trace-1",
        "payload": payload,
    }


def test_process_envelope_cria_conta_e_e_idempotente_por_event_id() -> None:
    db = _session()
    envelope = _envelope()

    resultado1 = process_onboarding_aprovado_envelope(db, envelope)
    resultado2 = process_onboarding_aprovado_envelope(db, envelope)  # reentrega do MESMO event_id

    assert resultado1 == "conta_criada"
    assert resultado2 == "duplicado_ignorado"

    count = db.execute(
        text("SELECT count(*) FROM accounts WHERE onboarding_id = :id"),
        {"id": envelope["payload"]["onboarding_id"]},
    ).scalar_one()
    assert count == 1

    processed_count = db.execute(
        text("SELECT count(*) FROM processed_events WHERE event_id = :id"), {"id": envelope["event_id"]}
    ).scalar_one()
    assert processed_count == 1  # segunda chamada nao insere de novo
    db.close()


def test_process_envelope_conta_ja_existente_com_event_id_diferente_nao_duplica() -> None:
    db = _session()
    onboarding_id = str(uuid.uuid4())
    envelope1 = _envelope(onboarding_id=onboarding_id)
    envelope2 = _envelope(onboarding_id=onboarding_id)  # event_id diferente, mesmo onboarding_id

    resultado1 = process_onboarding_aprovado_envelope(db, envelope1)
    resultado2 = process_onboarding_aprovado_envelope(db, envelope2)

    assert resultado1 == "conta_criada"
    assert resultado2 == "conta_ja_existia"  # defesa redundante por onboarding_id

    count = db.execute(
        text("SELECT count(*) FROM accounts WHERE onboarding_id = :id"), {"id": onboarding_id}
    ).scalar_one()
    assert count == 1
    db.close()


def test_process_envelope_persiste_cpf_cifrado_risco_e_tipo_conta_default() -> None:
    db = _session()
    envelope = _envelope()

    process_onboarding_aprovado_envelope(db, envelope)

    row = db.execute(
        text(
            "SELECT cpf, risco_score, risco_sinais, tipo_conta, status "
            "FROM accounts WHERE onboarding_id = :id"
        ),
        {"id": envelope["payload"]["onboarding_id"]},
    ).one()
    assert row.cpf != "12345678901"  # cifrado em repouso (issue #10)
    assert float(row.risco_score) == 10.0
    assert row.risco_sinais == ["dados_inconsistentes"]
    assert row.tipo_conta == "corrente"  # default documentado - payload do evento nao tem tipo_conta
    assert row.status == "ativa"
    db.close()
