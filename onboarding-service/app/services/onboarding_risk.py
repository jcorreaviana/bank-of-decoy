"""Adaptador do onboarding-service para o motor de risco compartilhado
(specs/business/04-onboarding-risco.md).

A regra de negocio em si (pesos, limiares, hard-stop de fraude) foi
extraida para o pacote `risk_engine` (shared/risk_engine, issue #8),
compartilhado com o populador de volume - ambos precisam da mesma
classificacao, so a origem do input muda (aqui, um request HTTP real; la,
massa sintetica gerada direto no banco). Este modulo cuida so da parte que
o pacote compartilhado deliberadamente nao faz: consultar o HISTORICO no
banco para os dois sinais que dependem dele (documento reciclado, padrao
mula) e traduzir o payload Pydantic para o dataclass de input do motor.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from risk_engine.onboarding import OnboardingRiskInput, RiskResult, evaluate_onboarding_risk as _evaluate_risk

from app.models import Onboarding
from app.schemas.onboarding import OnboardingCreateRequest

__all__ = ["RiskResult", "check_documento_reciclado", "check_padrao_mula", "evaluate_onboarding_risk"]

_JANELA_DOCUMENTO_RECICLADO = timedelta(hours=24)
_JANELA_PADRAO_MULA = timedelta(minutes=10)


def check_documento_reciclado(
    db: Session, payload: OnboardingCreateRequest, exclude_id: uuid.UUID | None = None, agora: datetime | None = None
) -> bool:
    """Simulado: mesmo documento_numero vinculado a outro onboarding aprovado
    nas ultimas 24h."""
    referencia = agora or datetime.now(timezone.utc)
    janela_inicio = referencia - _JANELA_DOCUMENTO_RECICLADO
    stmt = select(Onboarding.id).where(
        Onboarding.documento_numero == payload.documento_numero,
        Onboarding.status == "aprovado",
        Onboarding.created_at >= janela_inicio,
        Onboarding.deleted_at.is_(None),
    )
    if exclude_id is not None:
        stmt = stmt.where(Onboarding.id != exclude_id)
    return db.scalar(stmt.limit(1)) is not None


def check_padrao_mula(
    db: Session, payload: OnboardingCreateRequest, exclude_id: uuid.UUID | None = None, agora: datetime | None = None
) -> bool:
    """Simulado: velocidade de cadastro atipica - outro onboarding recente
    compartilhando IP de origem ou dispositivo."""
    referencia = agora or datetime.now(timezone.utc)
    janela_inicio = referencia - _JANELA_PADRAO_MULA
    stmt = select(Onboarding.id).where(
        or_(Onboarding.ip_origem == payload.ip_origem, Onboarding.dispositivo_id == payload.dispositivo_id),
        Onboarding.created_at >= janela_inicio,
        Onboarding.deleted_at.is_(None),
    )
    if exclude_id is not None:
        stmt = stmt.where(Onboarding.id != exclude_id)
    return db.scalar(stmt.limit(1)) is not None


def evaluate_onboarding_risk(
    db: Session, payload: OnboardingCreateRequest, exclude_id: uuid.UUID | None = None
) -> RiskResult:
    agora = datetime.now(timezone.utc)
    risk_input = OnboardingRiskInput(
        cpf=payload.cpf,
        nome=payload.nome,
        data_nascimento=payload.data_nascimento,
        documento_numero=payload.documento_numero,
        ip_origem=payload.ip_origem,
        dispositivo_id=payload.dispositivo_id,
        referencia=agora.date(),
        documento_reciclado=check_documento_reciclado(db, payload, exclude_id=exclude_id, agora=agora),
        padrao_mula=check_padrao_mula(db, payload, exclude_id=exclude_id, agora=agora),
    )
    return _evaluate_risk(risk_input)
