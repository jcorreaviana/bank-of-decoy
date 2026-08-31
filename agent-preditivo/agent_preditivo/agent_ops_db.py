"""Acesso ao banco `agent_ops` (agent-ops-service/migrations) - reflete o
schema real via `MetaData.reflect` em vez de importar `app.models` do
agent-ops-service (mesmo motivo de scripts/db_writer.py: `app` e nome de
pacote reservado por servico, colidiria se importado no mesmo processo)."""

import uuid
from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import MetaData, Table, create_engine, insert, select, update
from sqlalchemy.engine import Engine

from agent_preditivo.config import get_settings

_engine: Engine | None = None
_flagged_signals: Table | None = None
_risk_decisions: Table | None = None


def _get_engine() -> Engine:
    """So publica nos globais `_engine`/`_flagged_signals`/`_risk_decisions`
    depois que `create_engine` + `reflect` tiverem os DOIS sucesso completo
    (mesmo padrao aplicado em agent_local/agent_ops_db.py pela issue #61,
    commit c19f764): a versao anterior atribuia `_engine` ANTES do
    `reflect()`. Se o `reflect()` do PRIMEIRO uso da vida do processo
    falhasse por qualquer motivo transitorio (o daemon roda em loop
    continuo, nunca reinicia entre ciclos), `_engine` ficava "envenenado"
    (nao-None) para sempre, mas `_flagged_signals`/`_risk_decisions`
    permaneciam `None` - toda chamada seguinte no mesmo processo pulava o
    bloco `if _engine is None` e caia direto em `select(None)`/`insert(None)`.
    Corrigido usando variaveis locais durante a montagem: uma falha em
    qualquer passo agora deixa os globais como se nada tivesse acontecido,
    permitindo retry limpo no proximo ciclo (issue #90)."""
    global _engine, _flagged_signals, _risk_decisions
    if _engine is None:
        engine = create_engine(get_settings().agent_ops_database_url, pool_pre_ping=True)
        metadata = MetaData()
        metadata.reflect(bind=engine, only=["flagged_signals", "risk_decisions"])
        _engine = engine
        _flagged_signals = metadata.tables["flagged_signals"]
        _risk_decisions = metadata.tables["risk_decisions"]
    return _engine


def find_open_signal(signal_type: str, service_name: str) -> dict | None:
    """Sinal ja sinalizado e ainda sem `resolved_at` para esse
    (signal_type, service_name) - usado para deduplicacao antes de agir
    (specs/business/13-agente-preditivo-registro.md)."""
    engine = _get_engine()
    stmt = select(_flagged_signals).where(
        _flagged_signals.c.signal_type == signal_type,
        _flagged_signals.c.service_name == service_name,
        _flagged_signals.c.resolved_at.is_(None),
    )
    with engine.connect() as conn:
        row = conn.execute(stmt).mappings().first()
    return dict(row) if row else None


def register_signal(signal_type: str, service_name: str, issue_number: int | None = None) -> uuid.UUID:
    """Registra um sinal novo (primeira deteccao) ou atualiza `last_seen_at`
    de um sinal em aberto ja existente (mesmo sinal, ainda ocorrendo)."""
    engine = _get_engine()
    agora = datetime.now(timezone.utc)
    existing = find_open_signal(signal_type, service_name)

    with engine.begin() as conn:
        if existing is not None:
            conn.execute(
                update(_flagged_signals)
                .where(_flagged_signals.c.id == existing["id"])
                .values(last_seen_at=agora, updated_at=agora, issue_number=issue_number or existing["issue_number"])
            )
            return existing["id"]

        signal_id = uuid.uuid4()
        conn.execute(
            insert(_flagged_signals).values(
                id=signal_id,
                signal_type=signal_type,
                service_name=service_name,
                first_seen_at=agora,
                last_seen_at=agora,
                issue_number=issue_number,
                resolved_at=None,
                created_at=agora,
                updated_at=agora,
            )
        )
        return signal_id


def record_risk_decision(
    issue_number: int,
    risk_score: float,
    threshold_used: float,
    service_criticality: str,
    decision: str,
    pr_number: int | None = None,
) -> None:
    """Auditoria de decisao (usado pelo agente local, issue #16 - deixado
    aqui tambem porque o schema e compartilhado; o agente preditivo nao
    grava aqui hoje, so flagged_signals)."""
    engine = _get_engine()
    agora = datetime.now(timezone.utc)
    with engine.begin() as conn:
        conn.execute(
            insert(_risk_decisions).values(
                id=uuid.uuid4(),
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


def list_open_signals(service_name: str | None = None) -> Iterable[dict]:
    engine = _get_engine()
    stmt = select(_flagged_signals).where(_flagged_signals.c.resolved_at.is_(None))
    if service_name is not None:
        stmt = stmt.where(_flagged_signals.c.service_name == service_name)
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(stmt).mappings().all()]
