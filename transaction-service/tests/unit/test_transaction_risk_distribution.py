"""Calibracao estatistica do gerador de risco da transacao
(specs/business/06-pixkey-transaction-crud.md): rodando sobre uma amostra
grande e deterministica (seed fixa) de transacoes sinteticas, o percentual
de "suspeita" deve ficar entre 1% e 2%.

destinatario_novo e velocidade_alta dependem de historico no banco (ja
cobertos isoladamente em test_transaction_risk.py); aqui usamos um duplo de
Session que sempre resolve para "sem novidade" (destinatario ja visto,
velocidade baixa) para isolar a calibracao dos sinais estatisticos (valor
atipico, horario atipico) contra volume, sem depender de banco real - mesma
tecnica de app/services/onboarding_risk.py (onboarding-service) em
test_onboarding_risk_distribution.py.
"""

import random
import uuid
from datetime import datetime, timedelta, timezone

from app.schemas.transaction import TransactionCreateRequest
from app.services.transaction_risk import evaluate_transaction_risk

AMOSTRA = 10_000
SEED = 20260826

# fracao deliberadamente injetada com valor E horario atipicos simultaneos -
# a unica combinacao que, sobre a base "sem historico" abaixo, cruza o
# limiar de suspeita (ver test_transaction_risk.py:
# test_limiar_suspeita_e_atingivel_por_pelo_menos_duas_combinacoes).
FRACAO_SUSPEITA_ALVO = 0.015  # ~150 em 10.000
FRACAO_VALOR_ATIPICO_LEVE = 0.01  # so valor atipico - nao cruza o limiar sozinho
FRACAO_HORARIO_ATIPICO_LEVE = 0.01  # so horario atipico - nao cruza o limiar sozinho


class _FakeDbBaseline:
    """Duplo de Session onde destinatario ja foi visto e velocidade e baixa
    - `0` serve as duas queries do gerador (destinatario_novo trata qualquer
    retorno != None como "ja visto"; velocidade_alta trata 0 como contagem
    baixa)."""

    def scalar(self, *_args, **_kwargs):
        return 0


def _gerar_payload_e_horario(rng: random.Random, indice: int) -> tuple[TransactionCreateRequest, datetime]:
    r = rng.random()
    valor = round(rng.uniform(10, 5_000), 2)
    agora = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(
        hours=rng.randint(0, 23), minutes=rng.randint(0, 59), seconds=indice % 60
    )

    if r < FRACAO_SUSPEITA_ALVO:
        valor = round(rng.uniform(20_001, 50_000), 2)
        agora = agora.replace(hour=3)
    elif r < FRACAO_SUSPEITA_ALVO + FRACAO_VALOR_ATIPICO_LEVE:
        valor = round(rng.uniform(20_001, 50_000), 2)
        agora = agora.replace(hour=14)
    elif r < FRACAO_SUSPEITA_ALVO + FRACAO_VALOR_ATIPICO_LEVE + FRACAO_HORARIO_ATIPICO_LEVE:
        agora = agora.replace(hour=3)

    payload = TransactionCreateRequest(
        account_id=uuid.uuid4(), pix_key_destino=f"destino{indice}@example.com", valor=valor
    )
    return payload, agora


def test_percentual_suspeita_fica_entre_1_e_2_porcento_em_amostra_grande() -> None:
    rng = random.Random(SEED)
    db = _FakeDbBaseline()

    suspeitas = 0
    concluidas_com_sinal_leve = 0

    for i in range(AMOSTRA):
        payload, agora = _gerar_payload_e_horario(rng, i)
        result = evaluate_transaction_risk(db, payload, payload.account_id, agora=agora)

        assert result.status in ("concluida", "suspeita")
        assert result.score >= 0.0

        if result.status == "suspeita":
            suspeitas += 1
        elif result.sinais:
            concluidas_com_sinal_leve += 1

    percentual_suspeita = suspeitas / AMOSTRA

    assert 0.01 <= percentual_suspeita <= 0.02, (
        f"percentual de suspeita de {percentual_suspeita:.4%} fora da faixa [1%, 2%] "
        f"({suspeitas} de {AMOSTRA})"
    )
    assert concluidas_com_sinal_leve > 0
