"""Geracao pura da massa sintetica do populador de volume
(specs/business/08-populador-volume.md) - sem banco, sem I/O, so
construcao de registros + classificacao via risk_engine (shared/risk_engine,
issue #8). Mantido separado de db_writer.py para que a distribuicao
estatistica seja testavel em uma amostra pequena sem tocar Postgres (ver
scripts/tests/test_generation_distribution.py e o criterio de aceite da
issue #8: "teste automatizado valida a distribuicao... antes de rodar a
carga completa de 500k").

Nota sobre unicidade: `onboardings.cpf_hash` tem indice unico parcial
(specs/tech/database.md via 02-modelo-dados.md) - diferente do teste de
calibracao original em shared/risk_engine (populacao pequena, sem banco
real), aqui o cpf de CADA onboarding precisa ser unico de verdade. Os 3
CPFs de PEP simulados (risk_engine.onboarding.CPFS_PEP_SIMULADOS) so podem
aparecer no maximo uma vez cada — o restante da fracao de fraude usa
`ip_dispositivo_blacklist` (ip_origem/dispositivo_id nao tem restricao de
unicidade nenhuma), que produz o mesmo hard-stop de fraude sem esbarrar em
nenhuma constraint.
"""

import random
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from risk_engine.onboarding import CPFS_PEP_SIMULADOS, OnboardingRiskInput, evaluate_onboarding_risk
from risk_engine.transaction import TransactionRiskInput, evaluate_transaction_risk

# --- calibracao de onboarding (mesmas fracoes de
# shared/risk_engine/tests/unit/test_onboarding_risk_distribution.py,
# validadas ali para produzir 0.5%-1% de reprovacao combinada) ---
FRACAO_FRAUDE = 0.002
FRACAO_QUALIDADE_REPROVADA = 0.006
FRACAO_QUALIDADE_LEVE = 0.01

_BLACKLIST_IPS = ["198.51.100.66", "203.0.113.66"]
_BLACKLIST_DEVICES = ["device-blacklist-1", "device-blacklist-2"]
_PEP_CPFS_ORDENADOS = sorted(CPFS_PEP_SIMULADOS)  # frozenset nao e indexavel - ordem fixa e deterministica

# --- calibracao de transacao (mesmas fracoes de
# shared/risk_engine/tests/unit/test_transaction_risk_distribution.py,
# validadas ali para produzir 1%-2% de suspeita) ---
FRACAO_TRANSACAO_SUSPEITA_ALVO = 0.015
FRACAO_TRANSACAO_VALOR_ATIPICO_LEVE = 0.01
FRACAO_TRANSACAO_HORARIO_ATIPICO_LEVE = 0.01

TIPO_CONTA_CORRENTE_PESO = 0.7  # 70% corrente / 30% poupanca - diversidade de dados, sem exigencia de spec
PIX_KEY_TIPOS = ["cpf", "email", "telefone", "aleatoria"]

TRANSACOES_POR_CONTA_MIN = 20
TRANSACOES_POR_CONTA_MAX = 50


@dataclass(frozen=True)
class OnboardingRecord:
    id: uuid.UUID
    cpf: str  # texto puro - cifrado so na camada de escrita (db_writer.py)
    nome: str
    data_nascimento: date
    email: str
    telefone: str
    documento_tipo: str
    documento_numero: str
    dispositivo_id: str
    ip_origem: str
    status: str
    motivo_reprovacao: str | None
    risco_score: float
    risco_sinais: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class AccountRecord:
    id: uuid.UUID
    onboarding_id: uuid.UUID
    cpf: str  # texto puro - cifrado so na camada de escrita
    status: str
    tipo_conta: str
    risco_score: float
    risco_sinais: list[str]
    created_at: datetime


@dataclass(frozen=True)
class PixKeyRecord:
    id: uuid.UUID
    account_id: uuid.UUID
    tipo: str
    valor: str
    created_at: datetime


@dataclass(frozen=True)
class TransactionRecord:
    id: uuid.UUID
    account_id: uuid.UUID
    pix_key_destino: str
    valor: float
    status: str
    risco_score: float
    risco_sinais: list[str]
    created_at: datetime


def _cpf_sintetico(indice: int) -> str:
    """CPF sintetico unico e obviamente nao-real (specs/tech/testing.md:
    "sem uso de CPF... reais em fixtures") - 11 digitos, derivado do
    indice, nunca reaproveitado entre dois onboardings."""
    return f"{10_000_000_000 + indice:011d}"


def _data_nascimento_adulta(rng: random.Random, referencia: date) -> date:
    dias = rng.randint(18 * 365, 85 * 365)
    return referencia - timedelta(days=dias)


def _timestamp_no_periodo(rng: random.Random, agora: datetime, janela_dias: int) -> datetime:
    offset_segundos = rng.randint(0, janela_dias * 86_400)
    return agora - timedelta(seconds=offset_segundos)


def gerar_onboarding(rng: random.Random, indice: int, agora: datetime, janela_dias: int = 180) -> OnboardingRecord:
    referencia = agora.date()
    cpf = _cpf_sintetico(indice)
    nome = "Fulano DaSilva"
    data_nascimento = _data_nascimento_adulta(rng, referencia)
    documento_numero = f"DOC{indice:09d}"
    ip_origem = f"10.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(0, 255)}"
    dispositivo_id = f"device-{indice}"

    if indice < len(_PEP_CPFS_ORDENADOS):
        # os 3 primeiros indices ficam reservados, um para cada CPF de PEP
        # simulado - o unico sinal de fraude ligado ao VALOR do cpf, entao
        # so pode aparecer uma vez cada sem violar `onboardings.cpf_hash`
        # (unico). Nao entra na contagem de FRACAO_FRAUDE por r (3 em
        # 500k+ e desprezivel para a calibracao) - so garante que o sinal
        # apareca pelo menos uma vez na massa gerada, para diversidade.
        cpf = _PEP_CPFS_ORDENADOS[indice]

    r = rng.random()
    if r < FRACAO_FRAUDE:
        # metade da fracao de fraude via IP, metade via dispositivo -
        # nenhum dos dois exige unicidade (diferente do cpf de PEP).
        if rng.random() < 0.5:
            ip_origem = rng.choice(_BLACKLIST_IPS)
        else:
            dispositivo_id = rng.choice(_BLACKLIST_DEVICES)
    elif r < FRACAO_FRAUDE + FRACAO_QUALIDADE_REPROVADA:
        documento_numero = "!"  # dispara documento_formato_invalido
        nome = "Fulano2"  # dispara dados_inconsistentes -> soma 55 >= 50
    elif r < FRACAO_FRAUDE + FRACAO_QUALIDADE_REPROVADA + FRACAO_QUALIDADE_LEVE:
        documento_numero = "!"  # so documento_formato_invalido (30) - abaixo do limiar

    risk_input = OnboardingRiskInput(
        cpf=cpf,
        nome=nome,
        data_nascimento=data_nascimento,
        documento_numero=documento_numero,
        ip_origem=ip_origem,
        dispositivo_id=dispositivo_id,
        referencia=referencia,
    )
    risk = evaluate_onboarding_risk(risk_input)

    return OnboardingRecord(
        id=uuid.uuid4(),
        cpf=cpf,
        nome=nome,
        data_nascimento=data_nascimento,
        email=f"user{indice}@example.com",
        telefone="11999999999",
        documento_tipo="rg",
        documento_numero=documento_numero,
        dispositivo_id=dispositivo_id,
        ip_origem=ip_origem,
        status=risk.status,
        motivo_reprovacao=risk.motivo_reprovacao,
        risco_score=risk.score,
        risco_sinais=risk.sinais,
        created_at=_timestamp_no_periodo(rng, agora, janela_dias),
    )


def gerar_conta_e_pix_key(
    rng: random.Random, indice: int, onboarding: OnboardingRecord
) -> tuple[AccountRecord, PixKeyRecord]:
    account_id = uuid.uuid4()
    tipo_conta = "corrente" if rng.random() < TIPO_CONTA_CORRENTE_PESO else "poupanca"
    account_created_at = onboarding.created_at + timedelta(seconds=rng.randint(1, 120))

    account = AccountRecord(
        id=account_id,
        onboarding_id=onboarding.id,
        cpf=onboarding.cpf,
        status="ativa",
        tipo_conta=tipo_conta,
        risco_score=onboarding.risco_score,
        risco_sinais=onboarding.risco_sinais,
        created_at=account_created_at,
    )

    tipo = PIX_KEY_TIPOS[indice % len(PIX_KEY_TIPOS)]
    if tipo == "cpf":
        valor = onboarding.cpf
    elif tipo == "email":
        valor = f"conta{indice}@example.com"
    elif tipo == "telefone":
        valor = f"119{indice:08d}"[-11:]
    else:
        valor = f"aleatoria-{account_id}"

    pix_key = PixKeyRecord(
        id=uuid.uuid4(),
        account_id=account_id,
        tipo=tipo,
        valor=valor,
        created_at=account_created_at + timedelta(seconds=1),
    )
    return account, pix_key


def gerar_transacoes(rng: random.Random, account: AccountRecord, agora: datetime) -> Iterator[TransactionRecord]:
    quantidade = rng.randint(TRANSACOES_POR_CONTA_MIN, TRANSACOES_POR_CONTA_MAX)
    momento = account.created_at

    for j in range(quantidade):
        incremento = timedelta(seconds=rng.randint(3_600, 3 * 86_400))
        momento = min(momento + incremento, agora)

        valor = round(rng.uniform(10, 5_000), 2)
        destino = f"dest{rng.randint(0, 10_000_000)}@example.com"

        r = rng.random()
        if r < FRACAO_TRANSACAO_SUSPEITA_ALVO:
            valor = round(rng.uniform(20_001, 50_000), 2)
            momento = momento.replace(hour=3)
        elif r < FRACAO_TRANSACAO_SUSPEITA_ALVO + FRACAO_TRANSACAO_VALOR_ATIPICO_LEVE:
            valor = round(rng.uniform(20_001, 50_000), 2)
        elif r < (
            FRACAO_TRANSACAO_SUSPEITA_ALVO
            + FRACAO_TRANSACAO_VALOR_ATIPICO_LEVE
            + FRACAO_TRANSACAO_HORARIO_ATIPICO_LEVE
        ):
            momento = momento.replace(hour=3)

        risk_input = TransactionRiskInput(valor=valor, hora=momento.hour)
        risk = evaluate_transaction_risk(risk_input)

        yield TransactionRecord(
            id=uuid.uuid4(),
            account_id=account.id,
            pix_key_destino=destino,
            valor=valor,
            status=risk.status,
            risco_score=risk.score,
            risco_sinais=risk.sinais,
            created_at=momento,
        )
