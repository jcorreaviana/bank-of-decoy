"""Teste de integracao contra o agent_ops real (nao ha TRUNCATE aqui - so
insert/update de uma linha isolada por signal_type/service_name claramente
marcados como teste, removida ao final - risco bem menor que os fixtures
de TRUNCATE dos outros servicos, mas ainda assim tratado com cuidado
apos o incidente documentado em specs/tech/testing.md)."""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from agent_preditivo import agent_ops_db
from agent_preditivo.config import get_settings

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not os.environ.get("AGENT_OPS_DATABASE_URL"),
    reason="AGENT_OPS_DATABASE_URL nao configurada - teste requer banco agent_ops real.",
)


@pytest.fixture(autouse=True)
def _clean_test_signal():
    signal_type = "teste_unitario_dedup"
    service_name = f"servico-teste-{uuid.uuid4()}"
    yield signal_type, service_name
    engine = create_engine(settings.agent_ops_database_url)
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM flagged_signals WHERE signal_type = :st AND service_name = :sn"),
            {"st": signal_type, "sn": service_name},
        )


def test_find_open_signal_retorna_none_quando_nao_existe(_clean_test_signal) -> None:
    signal_type, service_name = _clean_test_signal
    assert agent_ops_db.find_open_signal(signal_type, service_name) is None


def test_register_signal_depois_find_open_signal_encontra(_clean_test_signal) -> None:
    signal_type, service_name = _clean_test_signal

    agent_ops_db.register_signal(signal_type, service_name, issue_number=999)
    found = agent_ops_db.find_open_signal(signal_type, service_name)

    assert found is not None
    assert found["issue_number"] == 999


def test_register_signal_chamado_duas_vezes_atualiza_last_seen_sem_duplicar(_clean_test_signal) -> None:
    signal_type, service_name = _clean_test_signal

    first_id = agent_ops_db.register_signal(signal_type, service_name)
    second_id = agent_ops_db.register_signal(signal_type, service_name)

    assert first_id == second_id
