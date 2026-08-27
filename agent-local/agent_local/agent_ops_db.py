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
    global _engine, _risk_decisions
    if _engine is None:
        _engine = create_engine(get_settings().agent_ops_database_url, pool_pre_ping=True)
        metadata = MetaData()
        metadata.reflect(bind=_engine, only=["risk_decisions"])
        _risk_decisions = metadata.tables["risk_decisions"]
    return _engine


def record_risk_decision(
    issue_number: int,
    risk_score: float,
    threshold_used: float,
    service_criticality: str,
    decision: str,
    pr_number: int | None = None,
) -> uuid.UUID:
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
                created_at=agora,
            )
        )
    return decision_id
