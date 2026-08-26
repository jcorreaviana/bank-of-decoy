import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import PixKey

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.database_url,
    reason="DATABASE_URL nao configurada - teste de migration requer banco real.",
)


def test_soft_delete_does_not_remove_row_physically() -> None:
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        pix_key = PixKey(
            id=uuid.uuid4(),
            account_id=uuid.uuid4(),
            tipo="email",
            valor="soft-delete-test@example.com",
        )
        session.add(pix_key)
        session.flush()
        pix_key_id = pix_key.id

        pix_key.deleted_at = datetime.now(timezone.utc)
        session.flush()

        raw_count = session.execute(
            text("SELECT count(*) FROM pix_keys WHERE id = :id"), {"id": str(pix_key_id)}
        ).scalar_one()
        assert raw_count == 1

        refreshed = session.scalar(select(PixKey).where(PixKey.id == pix_key_id))
        assert refreshed is not None
        assert refreshed.deleted_at is not None

        session.rollback()
