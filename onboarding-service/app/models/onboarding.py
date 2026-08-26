import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Onboarding(Base):
    __tablename__ = "onboardings"
    __table_args__ = (
        Index(
            "ix_onboardings_cpf_unique_not_deleted",
            "cpf",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cpf: Mapped[str] = mapped_column(String, nullable=False)
    nome: Mapped[str] = mapped_column(String, nullable=False)
    data_nascimento: Mapped[date] = mapped_column(Date, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    telefone: Mapped[str] = mapped_column(String, nullable=False)
    documento_tipo: Mapped[str] = mapped_column(String, nullable=False)
    documento_numero: Mapped[str] = mapped_column(String, nullable=False)
    dispositivo_id: Mapped[str] = mapped_column(String, nullable=False)
    ip_origem: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="em_analise")
    motivo_reprovacao: Mapped[str | None] = mapped_column(String, nullable=True)
    risco_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    risco_sinais: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
