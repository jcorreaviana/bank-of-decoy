"""Gerador de risco do onboarding (specs/business/04-onboarding-risco.md).

Regras deterministicas e simuladas para fins de estudo. Nesta fase nao ha
fonte de dado real para PEP, documento reciclado, padrao mula ou blacklist
de IP/dispositivo - cada avaliador abaixo e um substituto simples e
explicavel, facilmente trocavel por uma integracao real ou por um modelo de
ML no futuro (ver especs da Fase 2+).
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Onboarding
from app.schemas.onboarding import OnboardingCreateRequest

# --- Sinais de qualidade: resolviveis, cada um soma pontos ao score ---

PESO_DOCUMENTO_FORMATO_INVALIDO = 30
PESO_DADOS_INCONSISTENTES = 25
PESO_DOCUMENTO_ILEGIVEL = 20
LIMIAR_REPROVACAO_QUALIDADE = 50

IDADE_MINIMA = 18

# --- Sinais de fraude/compliance simulados: qualquer um e hard stop ---

_CPFS_PEP_SIMULADOS = frozenset({"11111111111", "22222222222", "33333333333"})
_IPS_BLACKLIST_SIMULADOS = frozenset({"198.51.100.66", "203.0.113.66"})
_DISPOSITIVOS_BLACKLIST_SIMULADOS = frozenset({"device-blacklist-1", "device-blacklist-2"})

_JANELA_DOCUMENTO_RECICLADO = timedelta(hours=24)
_JANELA_PADRAO_MULA = timedelta(minutes=10)


@dataclass(frozen=True)
class RiskResult:
    status: str
    score: float
    sinais: list[str]
    motivo_reprovacao: str | None


def _calcular_idade(data_nascimento: date, referencia: date) -> int:
    idade = referencia.year - data_nascimento.year
    if (referencia.month, referencia.day) < (data_nascimento.month, data_nascimento.day):
        idade -= 1
    return idade


def check_documento_formato_invalido(payload: OnboardingCreateRequest) -> bool:
    """Simulado: numero do documento deve ser alfanumerico, com 5 a 20 caracteres."""
    numero = payload.documento_numero.strip()
    return not (5 <= len(numero) <= 20 and numero.isalnum())


def check_dados_inconsistentes(payload: OnboardingCreateRequest, hoje: date | None = None) -> bool:
    """Simulado: sem OCR/registro real do documento nesta fase, usamos idade
    minima e uma heuristica simples de nome como proxy para "dados nao batem
    com o documento" (o cruzamento real exigiria extracao de dados do
    documento, fora do escopo desta simulacao).
    """
    referencia = hoje or datetime.now(timezone.utc).date()
    idade = _calcular_idade(payload.data_nascimento, referencia)
    nome_suspeito = len(payload.nome.strip().split()) < 2 or any(ch.isdigit() for ch in payload.nome)
    return idade < IDADE_MINIMA or nome_suspeito


def check_documento_ilegivel(payload: OnboardingCreateRequest) -> bool:
    """Simulado: numero de documento vazio (apos strip) conta como ilegivel."""
    return not payload.documento_numero.strip()


def check_pep_detectado(payload: OnboardingCreateRequest) -> bool:
    """Simulado: lista de bloqueio fixa no lugar de uma fonte real de PEP."""
    return payload.cpf in _CPFS_PEP_SIMULADOS


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


def check_ip_dispositivo_blacklist(payload: OnboardingCreateRequest) -> bool:
    """Simulado: lista de bloqueio fixa de IPs/dispositivos conhecidos."""
    return payload.ip_origem in _IPS_BLACKLIST_SIMULADOS or payload.dispositivo_id in _DISPOSITIVOS_BLACKLIST_SIMULADOS


def evaluate_onboarding_risk(
    db: Session, payload: OnboardingCreateRequest, exclude_id: uuid.UUID | None = None
) -> RiskResult:
    """Classifica um onboarding em aprovado/reprovado_qualidade/reprovado_fraude.

    1. Sinais de fraude sao avaliados primeiro - qualquer um presente e hard
       stop (score 100, sinais de qualidade nao chegam a ser avaliados).
    2. Sem sinal de fraude, os sinais de qualidade sao somados; soma >= 50
       reprova por qualidade.
    3. Caso contrario, aprovado - o score calculado e mantido mesmo assim,
       pois e dado relevante para o futuro modelo de risco.
    """
    fraud_signals: list[str] = []
    if check_pep_detectado(payload):
        fraud_signals.append("pep_detectado")
    if check_documento_reciclado(db, payload, exclude_id=exclude_id):
        fraud_signals.append("documento_reciclado")
    if check_padrao_mula(db, payload, exclude_id=exclude_id):
        fraud_signals.append("padrao_mula")
    if check_ip_dispositivo_blacklist(payload):
        fraud_signals.append("ip_dispositivo_blacklist")

    if fraud_signals:
        return RiskResult(
            status="reprovado_fraude",
            score=100.0,
            sinais=fraud_signals,
            motivo_reprovacao=fraud_signals[0],
        )

    quality_signals: list[str] = []
    score = 0.0
    if check_documento_formato_invalido(payload):
        quality_signals.append("documento_formato_invalido")
        score += PESO_DOCUMENTO_FORMATO_INVALIDO
    if check_dados_inconsistentes(payload):
        quality_signals.append("dados_inconsistentes")
        score += PESO_DADOS_INCONSISTENTES
    if check_documento_ilegivel(payload):
        quality_signals.append("documento_ilegivel")
        score += PESO_DOCUMENTO_ILEGIVEL

    if score >= LIMIAR_REPROVACAO_QUALIDADE:
        return RiskResult(
            status="reprovado_qualidade",
            score=score,
            sinais=quality_signals,
            motivo_reprovacao=quality_signals[0],
        )

    return RiskResult(status="aprovado", score=score, sinais=quality_signals, motivo_reprovacao=None)
