import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PixKey(Base):
    __tablename__ = "pix_keys"
    __table_args__ = (
        Index(
            "ix_pix_keys_valor_unique_not_deleted",
            "valor",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # issue #62 (latencia_alta): a unique index acima e parcial
        # (`deleted_at IS NULL`), entao nao cobre `get_by_valor_any`
        # (repositories/pix_key_repository.py), que busca por `valor` SEM
        # filtrar `deleted_at` - usada por GET /v1/pix-keys/lookup, chamada
        # sincrona no caminho critico de toda criacao de transacao
        # (transaction-service). Sem indice proprio, essa busca cai em
        # sequential scan da tabela inteira. Indice comum (nao unico, nao
        # parcial) em `valor` garante busca indexada independente do estado
        # de `deleted_at`.
        Index("ix_pix_keys_valor", "valor"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tipo: Mapped[str] = mapped_column(String, nullable=False)
    valor: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
