import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_value
from app.core.errors import (
    AccountAlreadyExistsError,
    AccountNotFoundError,
    OnboardingNotApprovedError,
    OnboardingNotFoundError,
)
from app.core.logging import get_logger, get_trace_id
from app.models import Account
from app.repositories import account_repository
from app.schemas.account import AccountCreateRequest
from app.services.onboarding_internal_client import (
    OnboardingNotFoundUpstreamError,
    fetch_onboarding_internal,
)

logger = get_logger(__name__)

_TIPO_CONTA_DEFAULT_EVENTO = "corrente"


def create_account(db: Session, payload: AccountCreateRequest) -> Account:
    """Rota operacional de reprocessamento manual (`POST /v1/accounts`) -
    NAO e mais o caminho do funil principal desde a issue #7: a criacao de
    conta a partir de um onboarding aprovado agora acontece automaticamente
    via `create_account_from_event`, disparada pelo consumidor Kafka de
    `onboarding.aprovado` (app/services/onboarding_event_consumer.py). Esta
    funcao existe para o caso operacional de precisar (re)criar uma conta
    manualmente (ex. evento perdido/corrompido) - por isso repete a MESMA
    checagem de aprovacao que o consumidor confia implicitamente no topico:
    aqui, como nao ha evento, a checagem e feita consultando o
    onboarding-service diretamente (chamada sincrona, unico lugar do
    servico que ainda faz isso)."""
    existing = account_repository.get_by_onboarding_id_active(db, payload.onboarding_id)
    if existing is not None:
        logger.warning(
            "Tentativa de criar conta para onboarding ja convertido.",
            extra={
                "context": {
                    "onboarding_id": str(payload.onboarding_id),
                    "existing_account_id": str(existing.id),
                }
            },
        )
        raise AccountAlreadyExistsError()

    logger.info(
        "Consultando onboarding-service (chamada sincrona) para criacao de conta.",
        extra={"context": {"onboarding_id": str(payload.onboarding_id)}},
    )
    try:
        onboarding = fetch_onboarding_internal(str(payload.onboarding_id), trace_id=get_trace_id())
    except OnboardingNotFoundUpstreamError:
        logger.warning(
            "Onboarding nao encontrado ao tentar criar conta.",
            extra={"context": {"onboarding_id": str(payload.onboarding_id)}},
        )
        raise OnboardingNotFoundError()

    if onboarding["status"] != "aprovado":
        logger.warning(
            "Tentativa de criar conta para onboarding nao aprovado.",
            extra={
                "context": {
                    "onboarding_id": str(payload.onboarding_id),
                    "onboarding_status": onboarding["status"],
                }
            },
        )
        raise OnboardingNotApprovedError()

    risco_cadastro = onboarding.get("risco_cadastro") or {}
    account = Account(
        onboarding_id=payload.onboarding_id,
        cpf=onboarding["cpf"],
        tipo_conta=payload.tipo_conta,
        status="ativa",
        risco_score=risco_cadastro.get("score"),
        risco_sinais=risco_cadastro.get("sinais") or [],
    )
    try:
        account = account_repository.create(db, account)
    except IntegrityError as exc:
        db.rollback()
        raise AccountAlreadyExistsError() from exc

    db.commit()

    logger.info(
        "Conta criada.",
        extra={"context": {"account_id": str(account.id), "onboarding_id": str(payload.onboarding_id)}},
    )

    return account


def get_account(db: Session, account_id: uuid.UUID) -> Account:
    account = account_repository.get_by_id_active(db, account_id)
    if account is None:
        raise AccountNotFoundError()
    return account


def create_account_from_event(db: Session, onboarding_id: uuid.UUID, payload: dict) -> Account:
    """Cria a conta a partir do payload do evento `onboarding.aprovado`
    (issue #7) - caminho principal do funil, disparado pelo consumidor
    Kafka. Diferente de `create_account`: nenhuma chamada de rede ao
    onboarding-service - o payload do evento ja traz `cpf` (cifrado),
    `risco_score` e `risco_sinais`, e o proprio topico `onboarding.aprovado`
    e o sinal de aprovacao (nao ha status para reconsultar).

    Nao comita: quem chama (app/services/onboarding_event_consumer.py)
    comita junto com o registro em `processed_events`, na mesma transacao -
    criar a conta e marcar o evento como processado precisam ser atomicos,
    senao uma queda do processo entre os dois passos reprocessaria o
    evento e tentaria criar a conta de novo (o indice unico parcial em
    `accounts.onboarding_id` ainda pegaria isso, mas o log ficaria
    confuso).

    `tipo_conta` nao existe no payload do evento - e uma escolha do
    cliente na rota REST original (issue #5), nao um dado do onboarding.
    Default "corrente" documentado aqui como decisao de implementacao;
    troca de tipo de conta fica para uma futura rota dedicada, fora do
    escopo desta issue."""
    existing = account_repository.get_by_onboarding_id_active(db, onboarding_id)
    if existing is not None:
        raise AccountAlreadyExistsError()

    account = Account(
        onboarding_id=onboarding_id,
        cpf=decrypt_value(payload["cpf"]),
        tipo_conta=_TIPO_CONTA_DEFAULT_EVENTO,
        status="ativa",
        risco_score=payload.get("risco_score"),
        risco_sinais=payload.get("risco_sinais") or [],
    )
    try:
        account = account_repository.create(db, account)
    except IntegrityError as exc:
        db.rollback()
        raise AccountAlreadyExistsError() from exc

    logger.info(
        "Conta criada a partir de evento onboarding.aprovado.",
        extra={"context": {"account_id": str(account.id), "onboarding_id": str(onboarding_id)}},
    )

    return account
