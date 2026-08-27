"""Calibracao estatistica do gerador de risco da transacao
(specs/business/06-pixkey-transaction-crud.md): rodando sobre uma amostra
grande e deterministica (seed fixa) de transacoes sinteticas, o percentual
de "suspeita" deve ficar entre 1% e 2%.

Mesmo teste de transaction-service/tests/unit/test_transaction_risk_distribution.py
antes da extracao (issue #8) - agora contra `TransactionRiskInput`
diretamente (destinatario_novo/velocidade_alta sempre False aqui, isolando
a calibracao dos sinais estatisticos - valor e horario atipicos - contra
volume, mesma tecnica de antes)."""

import random
from datetime import datetime, timedelta, timezone

from risk_engine.transaction import TransactionRiskInput, evaluate_transaction_risk

AMOSTRA = 10_000
SEED = 20260826

# fracao deliberadamente injetada com valor E horario atipicos simultaneos -
# a unica combinacao que, com destinatario_novo/velocidade_alta sempre
# False, cruza o limiar de suspeita.
FRACAO_SUSPEITA_ALVO = 0.015  # ~150 em 10.000
FRACAO_VALOR_ATIPICO_LEVE = 0.01  # so valor atipico - nao cruza o limiar sozinho
FRACAO_HORARIO_ATIPICO_LEVE = 0.01  # so horario atipico - nao cruza o limiar sozinho


def _gerar_input(rng: random.Random, indice: int) -> TransactionRiskInput:
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

    return TransactionRiskInput(valor=valor, hora=agora.hour)


def test_percentual_suspeita_fica_entre_1_e_2_porcento_em_amostra_grande() -> None:
    rng = random.Random(SEED)

    suspeitas = 0
    concluidas_com_sinal_leve = 0

    for i in range(AMOSTRA):
        risk_input = _gerar_input(rng, i)
        result = evaluate_transaction_risk(risk_input)

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
