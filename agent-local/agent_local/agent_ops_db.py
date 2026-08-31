"""Registro de auditoria em `risk_decisions` (database `agent_ops`)
(specs/business/14-agente-local.md, passo 7). Mesma abordagem de
agent-preditivo/agent_ops_db.py: reflete o schema real via
`MetaData.reflect` em vez de importar `app.models` do agent-ops-service
(pacote `app` e reservado por servico)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import MetaData, Table, create_engine, insert
from sqlalchemy.engine import Engine

from agent_local.config import get_settings

_engine: Engine | None = None
_risk_decisions: Table | None = None


def _get_engine() -> Engine:
    """So publica nos globais `_engine`/`_risk_decisions` depois que
    `create_engine` + `reflect` tiverem os DOIS sucesso completo (causa raiz
    real da issue #61, 1a falha genuina da janela de validacao Fase 2b -
    `docs/relatorio-janela-fase2b.md`, secao 10): a versao anterior
    atribuia `_engine` ANTES do `reflect()`. Se o `reflect()` do PRIMEIRO
    `record_risk_decision()` da vida do processo falhasse por qualquer
    motivo transitorio (o daemon roda em loop continuo, nunca reinicia
    entre ciclos - specs/tech/error-handling.md), `_engine` ficava
    "envenenado" (nao-None) para sempre, mas `_risk_decisions` permanecia
    `None` - toda chamada seguinte no MESMO processo pulava o bloco `if
    _engine is None` e caia direto em `insert(_risk_decisions)` =
    `insert(None)`, levantando `sqlalchemy.exc.ArgumentError: subject table
    for an INSERT, UPDATE or DELETE expected, got None.` - uma mensagem que
    nao aponta pra causa real (a falha transitoria original, ja resolvida
    havia muito quando o sintoma aparece). Reproduzido isoladamente forcando
    `MetaData.reflect` a falhar uma vez (`tests/unit/test_agent_ops_db.py`).
    Corrigido usando variaveis locais durante a montagem: uma falha em
    qualquer passo agora deixa `_engine`/`_risk_decisions` como se nada
    tivesse acontecido, permitindo retry limpo no proximo ciclo."""
    global _engine, _risk_decisions
    if _engine is None:
        engine = create_engine(get_settings().agent_ops_database_url, pool_pre_ping=True)
        metadata = MetaData()
        metadata.reflect(bind=engine, only=["risk_decisions"])
        _engine = engine
        _risk_decisions = metadata.tables["risk_decisions"]
    return _engine


def record_risk_decision(
    issue_number: int,
    risk_score: float,
    threshold_used: float,
    service_criticality: str,
    decision: str,
    pr_number: int | None = None,
    total_cost_usd: float | None = None,
    sdk_duration_ms: int | None = None,
) -> uuid.UUID:
    """`total_cost_usd`/`sdk_duration_ms` (issue #80): custo e duracao da
    chamada ao Claude Agent SDK que originou esta decisao
    (`SDKInvocationResult`, sdk_invocation.py) - antes so iam para log,
    impedindo reconstruir custo por ciclo retroativamente."""
    engine = _get_engine()
    agora = datetime.now(timezone.utc)
    decision_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            insert(_risk_decisions).values(
                id=decision_id,
                issue_number=issue_number,
                pr_number=pr_number,
                risk_score=risk_score,
                threshold_used=threshold_used,
                service_criticality=service_criticality,
                decision=decision,
                decided_at=agora,
                total_cost_usd=total_cost_usd,
                sdk_duration_ms=sdk_duration_ms,
                created_at=agora,
            )
        )
    return decision_id
