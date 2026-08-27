from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ProcessedEvent(Base):
    """Ledger de idempotencia de consumo de eventos Kafka (specs/tech/messaging.md:
    "todo consumidor e idempotente: mantem registro dos event_id ja
    processados... e ignora reprocessamento do mesmo event_id"). Nao e uma
    entidade de dominio (fora do escopo de specs/business/02-modelo-dados.md)
    - sem soft delete, sem `updated_at`: e so um registro de "isto ja foi
    visto", nunca atualizado depois de criado."""

    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
