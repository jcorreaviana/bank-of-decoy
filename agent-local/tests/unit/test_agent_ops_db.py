import uuid

import pytest
from sqlalchemy import MetaData, text

from agent_local import agent_ops_db


@pytest.fixture(autouse=True)
def _reset_module_singleton():
    """`agent_ops_db._engine`/`_risk_decisions` sao globais de modulo (cache
    deliberado entre ciclos do daemon, ver docstring de `_get_engine`) - sem
    reset, um teste contaminaria o proximo (mesmo problema que motiva este
    arquivo: estado de processo sobrevivendo entre tentativas)."""
    agent_ops_db._engine = None
    agent_ops_db._risk_decisions = None
    yield
    agent_ops_db._engine = None
    agent_ops_db._risk_decisions = None


def _cleanup_row(decision_id: uuid.UUID) -> None:
    engine = agent_ops_db._get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM risk_decisions WHERE id = :id"), {"id": str(decision_id)})


def test_record_risk_decision_funciona_normalmente() -> None:
    """Caminho feliz, contra o Postgres real de `agent_ops` (docker-compose)
    - mesma abordagem do resto da suite (`test_git_ops.py`), sem mock do
    banco em si."""
    decision_id = agent_ops_db.record_risk_decision(
        issue_number=999999,
        risk_score=0.1,
        threshold_used=0.5,
        service_criticality="baixa",
        decision="no_action_needed",
    )
    assert decision_id is not None
    _cleanup_row(decision_id)


def test_falha_transitoria_no_primeiro_reflect_nao_envenena_o_singleton_para_sempre(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regressao real da issue #61 (1a falha genuina da janela de validacao
    Fase 2b, nunca investigada ate agora - `docs/relatorio-janela-fase2b.md`
    secao 10): antes da correcao, `_get_engine()` atribuia `_engine` ANTES
    de `metadata.reflect()` ter sucesso. Uma falha transitoria (rede,
    outage momentaneo) no PRIMEIRO `reflect()` da vida do processo deixava
    `_engine` setado (nao-None) mas `_risk_decisions` em `None` para
    sempre - toda chamada seguinte a `record_risk_decision()` no MESMO
    processo (o daemon roda em loop continuo, nunca reinicia entre ciclos)
    pulava o bloco de inicializacao e caia direto em
    `insert(_risk_decisions)` = `insert(None)`, levantando
    `sqlalchemy.exc.ArgumentError: subject table for an INSERT, UPDATE or
    DELETE expected, got None.` - exatamente o erro reportado na issue #61,
    sem relacao nenhuma com o codigo de pix-key-service que o agente estava
    tentando corrigir.

    Este teste forca o PRIMEIRO `reflect()` a falhar (simula a falha
    transitoria original) e confirma que uma tentativa SEGUINTE, no mesmo
    processo, ainda consegue se recuperar e gravar a decisao normalmente -
    em vez de falhar para sempre com o erro enganoso de tabela None."""
    original_reflect = MetaData.reflect
    call_count = {"n": 0}

    def _flaky_reflect(self, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("falha transitoria simulada (ex: rede, outage momentaneo do Postgres)")
        return original_reflect(self, *args, **kwargs)

    monkeypatch.setattr(MetaData, "reflect", _flaky_reflect)

    with pytest.raises(RuntimeError, match="falha transitoria simulada"):
        agent_ops_db.record_risk_decision(
            issue_number=999999,
            risk_score=0.1,
            threshold_used=0.5,
            service_criticality="baixa",
            decision="no_action_needed",
        )

    assert agent_ops_db._engine is None, (
        "uma falha no primeiro reflect() nao pode deixar _engine setado - "
        "isso e o que envenena o singleton e causa a issue #61"
    )
    assert agent_ops_db._risk_decisions is None

    # Tentativa seguinte, mesmo processo (mesmo padrao do daemon real: nao
    # reinicia entre ciclos) - deve se recuperar normalmente, nao repetir o
    # ArgumentError enganoso.
    decision_id = agent_ops_db.record_risk_decision(
        issue_number=999999,
        risk_score=0.1,
        threshold_used=0.5,
        service_criticality="baixa",
        decision="no_action_needed",
    )
    assert decision_id is not None
    _cleanup_row(decision_id)
