from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.errors import AccountNotActiveError
from app.core.logging import get_logger, get_trace_id
from app.models import Transaction
from app.repositories import transaction_repository
from app.schemas.transaction import TransactionCreateRequest
from app.services.account_client import AccountNotFoundUpstreamError, fetch_account
from app.services.transaction_risk import evaluate_transaction_risk

logger = get_logger(__name__)


def create_transaction(db: Session, payload: TransactionCreateRequest) -> Transaction:
    logger.info(
        "Consultando account-service (chamada sincrona) para validar conta de origem.",
        extra={"context": {"account_id": str(payload.account_id)}},
    )
    try:
        account = fetch_account(str(payload.account_id), trace_id=get_trace_id())
    except AccountNotFoundUpstreamError:
        logger.warning(
            "Conta inexistente ao tentar criar transacao.",
            extra={"context": {"account_id": str(payload.account_id)}},
        )
        raise AccountNotActiveError()

    if account["status"] != "ativa":
        logger.warning(
            "Tentativa de transacao para conta nao ativa.",
            extra={"context": {"account_id": str(payload.account_id), "account_status": account["status"]}},
        )
        raise AccountNotActiveError()

    agora = datetime.now(timezone.utc)
    risk = evaluate_transaction_risk(db, payload, payload.account_id, agora=agora)

    transaction = Transaction(
        account_id=payload.account_id,
        pix_key_destino=payload.pix_key_destino,
        valor=payload.valor,
        status=risk.status,
        risco_score=risk.score,
        risco_sinais=risk.sinais,
    )
    transaction = transaction_repository.create(db, transaction)
    db.commit()

    logger.info(
        "Transacao criada.",
        extra={
            "context": {
                "transaction_id": str(transaction.id),
                "account_id": str(payload.account_id),
                "status": transaction.status,
            }
        },
    )

    return transaction
