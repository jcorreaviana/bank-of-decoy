"""Gerador de risco do onboarding (specs/business/04-onboarding-risco.md).

Extraido de onboarding-service/app/services/onboarding_risk.py (issue #8)
para ser compartilhado com o populador de volume, que gera massa sintetica
diretamente no banco, sem passar pela API - ambos os consumidores precisam
da MESMA regra (pesos, limiares, hard-stop de fraude), so a origem do
input muda.

Design: este modulo e deliberadamente livre de banco/ORM/Pydantic. Os dois
sinais que originalmente exigiam uma consulta a historico (documento
reciclado, padrao mula) chegam aqui como booleanos ja calculados pelo
chamador (`OnboardingRiskInput.documento_reciclado`/`.padrao_mula`) -
quem sabe COMO obter esse booleano e o chamador: o onboarding-service
consulta o banco real por request (ver app/services/onboarding_risk.py
la), o populador decide diretamente ao gerar a massa (sem custo de uma
query por registro, inviavel em volume de centenas de milhares).

Regras deterministicas e simuladas para fins de estudo. Nesta fase nao ha
fonte de dado real para PEP, documento reciclado, padrao mula ou blacklist
de IP/dispositivo - cada avaliador abaixo e um substituto simples e
explicavel, facilmente trocavel por uma integracao real ou por um modelo de
ML no futuro (ver especs da Fase 2+).
"""

from dataclasses import dataclass
from datetime import date

# --- Sinais de qualidade: resolviveis, cada um soma pontos ao score ---

PESO_DOCUMENTO_FORMATO_INVALIDO = 30
PESO_DADOS_INCONSISTENTES = 25
PESO_DOCUMENTO_ILEGIVEL = 20
LIMIAR_REPROVACAO_QUALIDADE = 50

IDADE_MINIMA = 18

# --- Sinais de fraude/compliance simulados: qualquer um e hard stop ---

CPFS_PEP_SIMULADOS = frozenset({"11111111111", "22222222222", "33333333333"})
IPS_BLACKLIST_SIMULADOS = frozenset({"198.51.100.66", "203.0.113.66"})
DISPOSITIVOS_BLACKLIST_SIMULADOS = frozenset({"device-blacklist-1", "device-blacklist-2"})


@dataclass(frozen=True)
class OnboardingRiskInput:
    cpf: str
    nome: str
    data_nascimento: date
    documento_numero: str
    ip_origem: str
    dispositivo_id: str
    referencia: date
    """Data de referencia para calculo de idade - explicita (nunca
    `date.today()` implicito) para manter a avaliacao pura/deterministica."""
    documento_reciclado: bool = False
    """Mesmo documento_numero vinculado a outro onboarding aprovado nas
    ultimas 24h - calculado pelo chamador (consulta real ou decisao direta
    de geracao sintetica)."""
    padrao_mula: bool = False
    """Outro onboarding recente compartilhando ip_origem/dispositivo_id -
    mesma observacao acima."""


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


def check_documento_formato_invalido(documento_numero: str) -> bool:
    """Simulado: numero do documento deve ser alfanumerico, com 5 a 20 caracteres."""
    numero = documento_numero.strip()
    return not (5 <= len(numero) <= 20 and numero.isalnum())


def check_dados_inconsistentes(nome: str, data_nascimento: date, referencia: date) -> bool:
    """Simulado: sem OCR/registro real do documento nesta fase, usamos idade
    minima e uma heuristica simples de nome como proxy para "dados nao batem
    com o documento" (o cruzamento real exigiria extracao de dados do
    documento, fora do escopo desta simulacao).
    """
    idade = _calcular_idade(data_nascimento, referencia)
    nome_suspeito = len(nome.strip().split()) < 2 or any(ch.isdigit() for ch in nome)
    return idade < IDADE_MINIMA or nome_suspeito


def check_documento_ilegivel(documento_numero: str) -> bool:
    """Simulado: numero de documento vazio (apos strip) conta como ilegivel."""
    return not documento_numero.strip()


def check_pep_detectado(cpf: str) -> bool:
    """Simulado: lista de bloqueio fixa no lugar de uma fonte real de PEP."""
    return cpf in CPFS_PEP_SIMULADOS


def check_ip_dispositivo_blacklist(ip_origem: str, dispositivo_id: str) -> bool:
    """Simulado: lista de bloqueio fixa de IPs/dispositivos conhecidos."""
    return ip_origem in IPS_BLACKLIST_SIMULADOS or dispositivo_id in DISPOSITIVOS_BLACKLIST_SIMULADOS


def evaluate_onboarding_risk(input: OnboardingRiskInput) -> RiskResult:
    """Classifica um onboarding em aprovado/reprovado_qualidade/reprovado_fraude.

    1. Sinais de fraude sao avaliados primeiro - qualquer um presente e hard
       stop (score 100, sinais de qualidade nao chegam a ser avaliados).
    2. Sem sinal de fraude, os sinais de qualidade sao somados; soma >= 50
       reprova por qualidade.
    3. Caso contrario, aprovado - o score calculado e mantido mesmo assim,
       pois e dado relevante para o futuro modelo de risco.
    """
    fraud_signals: list[str] = []
    if check_pep_detectado(input.cpf):
        fraud_signals.append("pep_detectado")
    if input.documento_reciclado:
        fraud_signals.append("documento_reciclado")
    if input.padrao_mula:
        fraud_signals.append("padrao_mula")
    if check_ip_dispositivo_blacklist(input.ip_origem, input.dispositivo_id):
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
    if check_documento_formato_invalido(input.documento_numero):
        quality_signals.append("documento_formato_invalido")
        score += PESO_DOCUMENTO_FORMATO_INVALIDO
    if check_dados_inconsistentes(input.nome, input.data_nascimento, input.referencia):
        quality_signals.append("dados_inconsistentes")
        score += PESO_DADOS_INCONSISTENTES
    if check_documento_ilegivel(input.documento_numero):
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
