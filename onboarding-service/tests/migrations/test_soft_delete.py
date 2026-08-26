import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Onboarding

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.database_url,
    reason="DATABASE_URL nao configurada - teste de migration requer banco real.",
)


def test_soft_delete_does_not_remove_row_physically() -> None:
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        onboarding = Onboarding(
            id=uuid.uuid4(),
            cpf="22222222222",
            nome="Teste Soft Delete",
            data_nascimento=date(1990, 1, 1),
            email="softdelete@example.com",
            telefone="11988887777",
            documento_tipo="rg",
            documento_numero="999",
            dispositivo_id="dev-test",
            ip_origem="10.0.0.1",
            status="em_analise",
        )
        session.add(onboarding)
        session.flush()
        onboarding_id = onboarding.id

        onboarding.deleted_at = datetime.now(timezone.utc)
        session.flush()

        raw_count = session.execute(
            text("SELECT count(*) FROM onboardings WHERE id = :id"), {"id": str(onboarding_id)}
        ).scalar_one()
        assert raw_count == 1

        refreshed = session.scalar(select(Onboarding).where(Onboarding.id == onboarding_id))
        assert refreshed is not None
        assert refreshed.deleted_at is not None

        session.rollback()
