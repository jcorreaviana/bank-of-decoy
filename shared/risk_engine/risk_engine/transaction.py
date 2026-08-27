"""Gerador de risco da transacao (specs/business/06-pixkey-transaction-crud.md).

Extraido de transaction-service/app/services/transaction_risk.py (issue #8)
para ser compartilhado com o populador de volume - mesma motivacao de
risk_engine/onboarding.py: a regra (pesos, limiar, combinacao de sinais)
vive aqui, livre de banco/ORM/Pydantic; os dois sinais que dependiam de
consulta a historico (destinatario novo, velocidade alta) chegam como
booleanos ja calculados por quem chama.

Mesma filosofia de risk_engine/onboarding.py: regras deterministicas e
simuladas, nao ML. A spec deixa em aberto como "a combinacao de sinais
determina risco_score" e trata "status: suspeita" como derivado dessa
combinacao - aqui, cada sinal contribui um peso e a soma cruzando um
limiar decide o status (mesmo padrao de soma+limiar do onboarding), o que
evita marcar toda transacao para um destinatario novo como suspeita
isoladamente.
"""

from dataclasses import dataclass

PESO_VALOR_ATIPICO = 40
PESO_HORARIO_ATIPICO = 25
PESO_DESTINATARIO_NOVO = 20
PESO_VELOCIDADE_ALTA = 35
LIMIAR_SUSPEITA = 50

VALOR_ATIPICO_LIMIAR = 20_000.0
HORAS_ATIPICAS = frozenset({3})  # madrugada, 3h-4h


@dataclass(frozen=True)
class TransactionRiskInput:
    valor: float
    hora: int
    """Hora do dia (0-23) do momento da transacao - extraida pelo chamador
    de `datetime.hour`, mantendo este modulo livre de fuso/tz."""
    destinatario_novo: bool = False
    """Primeira transacao dessa conta para este pix_key_destino - calculado
    pelo chamador (consulta real ou decisao direta de geracao sintetica)."""
    velocidade_alta: bool = False
    """Varias transacoes da mesma conta em janela curta - mesma observacao
    acima."""


@dataclass(frozen=True)
class RiskResult:
    status: str
    score: float
    sinais: list[str]


def check_valor_atipico(valor: float) -> bool:
    return valor > VALOR_ATIPICO_LIMIAR


def check_horario_atipico(hora: int) -> bool:
    return hora in HORAS_ATIPICAS


def evaluate_transaction_risk(input: TransactionRiskInput) -> RiskResult:
    sinais: list[str] = []
    score = 0.0

    if check_valor_atipico(input.valor):
        sinais.append("valor_atipico")
        score += PESO_VALOR_ATIPICO
    if check_horario_atipico(input.hora):
        sinais.append("horario_atipico")
        score += PESO_HORARIO_ATIPICO
    if input.destinatario_novo:
        sinais.append("destinatario_novo")
        score += PESO_DESTINATARIO_NOVO
    if input.velocidade_alta:
        sinais.append("velocidade_alta")
        score += PESO_VELOCIDADE_ALTA

    status = "suspeita" if score >= LIMIAR_SUSPEITA else "concluida"
    return RiskResult(status=status, score=score, sinais=sinais)
