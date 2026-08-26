import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import EncryptedString
from app.core.db import Base


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        Index("ix_accounts_cpf", "cpf"),
        # Garante a nivel de banco a regra "so uma conta ativa por
        # onboarding" (specs/business/05-account-post-sincrono.md, 409
        # ACCOUNT_ALREADY_EXISTS) - sem isso, duas chamadas concorrentes
        # poderiam passar as duas pela checagem de aplicacao antes de
        # qualquer uma commitar.
        Index(
            "ix_accounts_onboarding_id_unique_not_deleted",
            "onboarding_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    onboarding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cpf: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    tipo_conta: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="ativa")
    risco_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    risco_sinais: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
