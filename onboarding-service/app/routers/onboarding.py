import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.onboarding import (
    OnboardingCreateRequest,
    OnboardingCreateResponse,
    OnboardingDetailResponse,
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
