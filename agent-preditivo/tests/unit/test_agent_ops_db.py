"""Teste de integracao contra o agent_ops real (nao ha TRUNCATE aqui - so
insert/update de uma linha isolada por signal_type/service_name claramente
marcados como teste, removida ao final - risco bem menor que os fixtures
de TRUNCATE dos outros servicos, mas ainda assim tratado com cuidado
apos o incidente documentado em specs/tech/testing.md)."""

import os
import uuid

import pytest
from sqlalchemy import MetaData, create_engine, text

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


@pytest.fixture(autouse=True)
def _reset_module_singleton():
    """`agent_ops_db._engine`/`_flagged_signals`/`_risk_decisions` sao
    globais de modulo (cache deliberado entre ciclos do daemon, ver
    docstring de `_get_engine`) - sem reset, um teste contaminaria o
    proximo (mesmo problema que motiva o teste de regressao abaixo)."""
    agent_ops_db._engine = None
    agent_ops_db._flagged_signals = None
    agent_ops_db._risk_decisions = None
    yield
    agent_ops_db._engine = None
    agent_ops_db._flagged_signals = None
    agent_ops_db._risk_decisions = None


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


def test_falha_transitoria_no_primeiro_reflect_nao_envenena_o_singleton_para_sempre(
    _clean_test_signal, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regressao da issue #90 (mesmo padrao estrutural ja corrigido em
    agent_local/agent_ops_db.py pela issue #61, commit c19f764): antes da
    correcao, `_get_engine()` atribuia `_engine` ANTES de
    `metadata.reflect()` ter sucesso. Uma falha transitoria (rede, outage
    momentaneo) no PRIMEIRO `reflect()` da vida do processo deixava
    `_engine` setado (nao-None) mas `_flagged_signals`/`_risk_decisions` em
    `None` para sempre - toda chamada seguinte a `register_signal()` ou
    `find_open_signal()` no MESMO processo (o daemon roda em loop continuo,
    nunca reinicia entre ciclos) pulava o bloco de inicializacao e caia
    direto em `select(None)`/`insert(None)`.

    Este teste forca o PRIMEIRO `reflect()` a falhar (simula a falha
    transitoria original) e confirma que uma tentativa SEGUINTE, no mesmo
    processo, ainda consegue se recuperar e gravar/ler o sinal normalmente -
    em vez de falhar para sempre."""
    signal_type, service_name = _clean_test_signal
    original_reflect = MetaData.reflect
    call_count = {"n": 0}

    def _flaky_reflect(self, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("falha transitoria simulada (ex: rede, outage momentaneo do Postgres)")
        return original_reflect(self, *args, **kwargs)

    monkeypatch.setattr(MetaData, "reflect", _flaky_reflect)

    with pytest.raises(RuntimeError, match="falha transitoria simulada"):
        agent_ops_db.register_signal(signal_type, service_name)

    assert agent_ops_db._engine is None, (
        "uma falha no primeiro reflect() nao pode deixar _engine setado - "
        "isso e o que envenena o singleton (mesmo padrao da issue #61)"
    )
    assert agent_ops_db._flagged_signals is None
    assert agent_ops_db._risk_decisions is None

    # Tentativa seguinte, mesmo processo (mesmo padrao do daemon real: nao
    # reinicia entre ciclos) - deve se recuperar normalmente.
    agent_ops_db.register_signal(signal_type, service_name, issue_number=999)
    found = agent_ops_db.find_open_signal(signal_type, service_name)
    assert found is not None
    assert found["issue_number"] == 999
