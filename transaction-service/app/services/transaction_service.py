import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.errors import (
    AccountNotActiveError,
    PixKeyDestinoInativaError,
    PixKeyDestinoNotFoundError,
    SaldoInsuficienteError,
)
from app.core.logging import get_logger, get_trace_id
from app.models import Transaction
from app.repositories import transaction_repository
from app.schemas.transaction import TransactionCreateRequest
from app.services.account_client import AccountNotFoundUpstreamError, fetch_account
from app.services.account_transfer_client import SaldoInsuficienteUpstreamError, transferir_saldo
from app.services.pix_key_client import PixKeyDestinoNotFoundUpstreamError, fetch_pix_key_by_valor
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

    logger.info(
        "Consultando pix-key-service (chamada sincrona) para validar chave de destino.",
        extra={"context": {"pix_key_destino": payload.pix_key_destino}},
    )
    try:
        pix_key_destino = fetch_pix_key_by_valor(payload.pix_key_destino, trace_id=get_trace_id())
    except PixKeyDestinoNotFoundUpstreamError:
        logger.warning(
            "Chave de destino inexistente ao tentar criar transacao.",
            extra={"context": {"pix_key_destino": payload.pix_key_destino}},
        )
        raise PixKeyDestinoNotFoundError()

    if not pix_key_destino["ativa"]:
        logger.warning(
            "Tentativa de transacao para chave de destino cancelada.",
            extra={"context": {"pix_key_destino": payload.pix_key_destino}},
        )
        raise PixKeyDestinoInativaError()

    conta_destino_id = uuid.UUID(pix_key_destino["account_id"])

    agora = datetime.now(timezone.utc)
    risk = evaluate_transaction_risk(db, payload, payload.account_id, agora=agora)

    logger.info(
        "Consultando account-service (chamada sincrona) para transferir saldo.",
        extra={"context": {"account_id": str(payload.account_id), "conta_destino_id": str(conta_destino_id)}},
    )
    try:
        transferir_saldo(payload.account_id, conta_destino_id, payload.valor, trace_id=get_trace_id())
    except SaldoInsuficienteUpstreamError:
        logger.warning(
            "Tentativa de transacao com saldo insuficiente.",
            extra={"context": {"account_id": str(payload.account_id), "valor": payload.valor}},
        )
        raise SaldoInsuficienteError()

    e2e_id = uuid.uuid4()
    saida = Transaction(
        e2e_id=e2e_id,
        tipo="saida",
        account_id=payload.account_id,
        contraparte_account_id=conta_destino_id,
        pix_key_destino=payload.pix_key_destino,
        valor=payload.valor,
        status=risk.status,
        risco_score=risk.score,
        risco_sinais=risk.sinais,
    )
    entrada = Transaction(
        e2e_id=e2e_id,
        tipo="entrada",
        account_id=conta_destino_id,
        contraparte_account_id=payload.account_id,
        pix_key_destino=payload.pix_key_destino,
        valor=payload.valor,
        status=risk.status,
        risco_score=None,
        risco_sinais=None,
    )
    saida, entrada = transaction_repository.create_par(db, saida, entrada)
    db.commit()

    logger.info(
        "Transacao criada (partida dobrada).",
        extra={
            "context": {
                "e2e_id": str(e2e_id),
                "transaction_id_saida": str(saida.id),
                "transaction_id_entrada": str(entrada.id),
                "account_id": str(payload.account_id),
                "conta_destino_id": str(conta_destino_id),
                "status": saida.status,
            }
        },
    )

    return saida
