import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RiskDecision(Base):
    __tablename__ = "risk_decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    issue_number: Mapped[int] = mapped_column(Integer, nullable=False)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    risk_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    threshold_used: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    service_criticality: Mapped[str] = mapped_column(String, nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    """Custo da chamada ao Claude Agent SDK que gerou esta decisao
    (`SDKInvocationResult.total_cost_usd`, agent-local/agent_local/sdk_invocation.py).
    Nullable porque decisoes registradas por outros agentes (ex.
    agent-preditivo) nao tem invocacao de SDK associada (issue #80)."""
    sdk_duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    """Duracao de parede da chamada ao SDK (`ResultMessage.duration_ms`),
    persistida junto com `total_cost_usd` para permitir reconstruir custo/
    tempo por ciclo retroativamente (issue #80) - antes so ia para log."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
