from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProcessedEvent


def is_processed(db: Session, event_id: str) -> bool:
    stmt = select(ProcessedEvent.event_id).where(ProcessedEvent.event_id == event_id)
    return db.scalar(stmt) is not None


def mark_processed(db: Session, event_id: str, event_type: str) -> None:
    db.add(ProcessedEvent(event_id=event_id, event_type=event_type))
    db.flush()
