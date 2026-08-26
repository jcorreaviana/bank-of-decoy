import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Account

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.database_url or not os.environ.get("CPF_ENCRYPTION_KEY"),
    reason="DATABASE_URL/CPF_ENCRYPTION_KEY nao configuradas - teste de migration requer banco real.",
)


def test_soft_delete_does_not_remove_row_physically() -> None:
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        account = Account(
            id=uuid.uuid4(),
            onboarding_id=uuid.uuid4(),
            cpf="33333333333",
            status="ativa",
        )
        session.add(account)
        session.flush()
        account_id = account.id

        account.deleted_at = datetime.now(timezone.utc)
        session.flush()

        raw_count = session.execute(
            text("SELECT count(*) FROM accounts WHERE id = :id"), {"id": str(account_id)}
        ).scalar_one()
        assert raw_count == 1

        refreshed = session.scalar(select(Account).where(Account.id == account_id))
        assert refreshed is not None
        assert refreshed.deleted_at is not None

        session.rollback()
