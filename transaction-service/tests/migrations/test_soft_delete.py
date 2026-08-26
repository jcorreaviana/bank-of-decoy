import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Transaction

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.database_url,
    reason="DATABASE_URL nao configurada - teste de migration requer banco real.",
)


def test_soft_delete_does_not_remove_row_physically() -> None:
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        transaction = Transaction(
            id=uuid.uuid4(),
            account_id=uuid.uuid4(),
            pix_key_destino="destino@example.com",
            valor=Decimal("150.00"),
            status="concluida",
        )
        session.add(transaction)
        session.flush()
        transaction_id = transaction.id

        transaction.deleted_at = datetime.now(timezone.utc)
        session.flush()

        raw_count = session.execute(
            text("SELECT count(*) FROM transactions WHERE id = :id"), {"id": str(transaction_id)}
        ).scalar_one()
        assert raw_count == 1

        refreshed = session.scalar(select(Transaction).where(Transaction.id == transaction_id))
        assert refreshed is not None
        assert refreshed.deleted_at is not None

        session.rollback()


def test_original_transaction_id_references_parent_transaction() -> None:
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        original = Transaction(
            id=uuid.uuid4(),
            account_id=uuid.uuid4(),
            pix_key_destino="destino@example.com",
            valor=Decimal("200.00"),
            status="concluida",
        )
        session.add(original)
        session.flush()

        reversal = Transaction(
            id=uuid.uuid4(),
            account_id=original.account_id,
            pix_key_destino="destino@example.com",
            valor=Decimal("200.00"),
            status="concluida",
            original_transaction_id=original.id,
        )
        session.add(reversal)
        session.flush()

        refreshed = session.scalar(select(Transaction).where(Transaction.id == reversal.id))
        assert refreshed is not None
        assert refreshed.original_transaction_id == original.id

        session.rollback()
