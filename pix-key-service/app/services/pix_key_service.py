import uuid

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AccountNotFoundError, PixKeyAlreadyRegisteredError, PixKeyNotFoundError
from app.core.logging import get_logger, get_trace_id
from app.core.metrics import chave_pix_registrada_total
from app.models import PixKey
from app.repositories import pix_key_repository
from app.schemas.pix_key import PixKeyCreateRequest

logger = get_logger(__name__)

_ACCOUNT_SERVICE_TIMEOUT_SECONDS = 5.0


class AccountNotFoundUpstreamError(Exception):
    """O account-service respondeu 404 - account_id inexistente ou deletado."""


class AccountServiceUnavailableError(Exception):
    """Falha na chamada sincrona ao account-service (timeout, conexao
    recusada, resposta inesperada)."""


def _fetch_account(account_id: str, trace_id: str = "") -> dict:
    """Cliente REST sincrono para o account-service (GET /v1/accounts/{id}),
    usado para validar que a conta existe antes de registrar uma chave PIX
    (docs/escopo-arquitetura.md - contrato original de POST /v1/pix-keys,
    erro 404 para conta inexistente). Mesma filosofia/versao provisoria e
    sincrona do cliente equivalente em transaction-service
    (app/services/account_client.py, issue #6): sem retry/circuit breaker
    sofisticado, uma falha aqui deve ficar visivel (log + erro), nao
    escondida atras de tentativas automaticas."""
    settings = get_settings()
    url = f"{settings.account_service_url}/v1/accounts/{account_id}"
    headers = {"X-Trace-Id": trace_id} if trace_id else {}

    try:
        response = httpx.get(url, headers=headers, timeout=_ACCOUNT_SERVICE_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        logger.error(
            "Falha na chamada sincrona ao account-service.",
            extra={"context": {"target_url": url, "account_id": account_id, "error": str(exc)}},
        )
        raise AccountServiceUnavailableError("account-service indisponivel") from exc

    if response.status_code == 404:
        raise AccountNotFoundUpstreamError()

    if response.status_code >= 400:
        logger.error(
            "Resposta inesperada do account-service.",
            extra={
                "context": {
                    "target_url": url,
                    "account_id": account_id,
                    "status_code": response.status_code,
                }
            },
        )
        raise AccountServiceUnavailableError("account-service retornou erro inesperado")

    return response.json()


def create_pix_key(db: Session, payload: PixKeyCreateRequest) -> PixKey:
    logger.info(
        "Consultando account-service (chamada sincrona) para validar conta.",
        extra={"context": {"account_id": str(payload.account_id)}},
    )
    try:
        _fetch_account(str(payload.account_id), trace_id=get_trace_id())
    except AccountNotFoundUpstreamError:
        logger.warning(
            "Conta inexistente ao tentar registrar chave PIX.",
            extra={"context": {"account_id": str(payload.account_id)}},
        )
        raise AccountNotFoundError()

    existing = pix_key_repository.get_by_valor_active(db, payload.valor)
    if existing is not None:
        logger.warning(
            "Tentativa de registrar chave PIX ja registrada.",
            extra={"context": {"existing_pix_key_id": str(existing.id)}},
        )
        raise PixKeyAlreadyRegisteredError()

    pix_key = PixKey(account_id=payload.account_id, tipo=payload.tipo, valor=payload.valor)
    try:
        pix_key = pix_key_repository.create(db, pix_key)
    except IntegrityError as exc:
        db.rollback()
        raise PixKeyAlreadyRegisteredError() from exc

    db.commit()

    chave_pix_registrada_total.labels(tipo=payload.tipo).inc()

    logger.info(
        "Chave PIX criada.",
        extra={"context": {"pix_key_id": str(pix_key.id), "account_id": str(payload.account_id)}},
    )

    return pix_key


def lookup_pix_key_by_valor(db: Session, valor: str) -> PixKey:
    pix_key = pix_key_repository.get_by_valor_any(db, valor)
    if pix_key is None:
        raise PixKeyNotFoundError()
    return pix_key


def delete_pix_key(db: Session, pix_key_id: uuid.UUID) -> None:
    pix_key = pix_key_repository.get_by_id_active(db, pix_key_id)
    if pix_key is None:
        raise PixKeyNotFoundError()

    pix_key_repository.soft_delete(db, pix_key)
    db.commit()

    logger.info("Chave PIX removida (soft delete).", extra={"context": {"pix_key_id": str(pix_key_id)}})
