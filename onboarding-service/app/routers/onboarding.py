import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.repositories import onboarding_repository
from app.schemas.onboarding import (
    OnboardingCreateRequest,
    OnboardingCreateResponse,
    OnboardingDetailResponse,
    OnboardingInternalResponse,
    RiscoCadastro,
)
from app.services.onboarding_service import create_onboarding, get_onboarding

router = APIRouter(prefix="/v1/onboarding", tags=["onboarding"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=OnboardingCreateResponse)
def post_onboarding(
    payload: OnboardingCreateRequest, db: Session = Depends(get_db)
) -> OnboardingCreateResponse:
    onboarding = create_onboarding(db, payload)
    return OnboardingCreateResponse(id=onboarding.id, status=onboarding.status, created_at=onboarding.created_at)


@router.get("/{onboarding_id}", response_model=OnboardingDetailResponse)
def get_onboarding_detail(
    onboarding_id: uuid.UUID, db: Session = Depends(get_db)
) -> OnboardingDetailResponse:
    onboarding = get_onboarding(db, onboarding_id)
    return OnboardingDetailResponse(
        id=onboarding.id,
        status=onboarding.status,
        risco_cadastro=RiscoCadastro(score=onboarding.risco_score, sinais=onboarding.risco_sinais or []),
        created_at=onboarding.created_at,
    )


@router.get("/{onboarding_id}/internal", response_model=OnboardingInternalResponse)
def get_onboarding_internal(
    onboarding_id: uuid.UUID, db: Session = Depends(get_db)
) -> OnboardingInternalResponse:
    """Uso EXCLUSIVO servico-a-servico (hoje, so o account-service).

    NAO expor publicamente: e a unica forma de outro servico obter o `cpf`
    do onboarding (ausente do GET publico, que so tem `risco_cadastro`),
    necessaria porque `accounts.cpf` precisa desse dado (ver
    specs/business/05-account-post-sincrono.md). O `cpf` retornado aqui
    continua no formato criptografado (ciphertext) - este servico nao
    decifra para servir esse endpoint, ver specs/business/10-criptografia-cpf.md.
    Sem autenticacao nesta fase (specs/tech/security.md); precisaria de
    autenticacao de servico antes de qualquer exposicao alem da rede
    interna do compose.
    """
    onboarding = get_onboarding(db, onboarding_id)
    raw_cpf = onboarding_repository.get_raw_cpf_ciphertext(db, onboarding_id)
    return OnboardingInternalResponse(
        id=onboarding.id,
        cpf=raw_cpf,
        status=onboarding.status,
        risco_cadastro=RiscoCadastro(score=onboarding.risco_score, sinais=onboarding.risco_sinais or []),
        created_at=onboarding.created_at,
    )
