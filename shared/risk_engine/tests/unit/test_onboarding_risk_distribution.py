"""Calibracao estatistica do gerador de risco (specs/business/04-onboarding-risco.md):
rodando sobre uma amostra grande e deterministica (seed fixa) de onboardings
sinteticos, o percentual combinado de reprovacao deve ficar entre 0,5% e 1%.

Mesmo teste de onboarding-service/tests/unit/test_onboarding_risk_distribution.py
antes da extracao (issue #8) - agora contra `OnboardingRiskInput` diretamente,
sem precisar de um duplo de Session (documento_reciclado/padrao_mula ja
chegam como booleano, sempre False aqui - isola a calibracao dos pesos/
limiares dos sinais estatisticos, mesma tecnica de antes)."""

import random
import string
from datetime import date, timedelta

from risk_engine.onboarding import OnboardingRiskInput, evaluate_onboarding_risk

AMOSTRA = 10_000
SEED = 20260826

# fracoes deliberadamente "ruins" injetadas na amostra sintetica - o restante
# e gerado limpo por construcao (nunca dispara nenhum sinal). Sem essa
# injecao controlada, dados puramente aleatorios quase nunca colidiriam com
# as blacklists fixas (o gerador de risco simulado nao tem uma fonte real de
# fraude para aprender variacao).
FRACAO_PEP = 0.001  # ~10 em 10.000
FRACAO_BLACKLIST = 0.001  # ~10 em 10.000
FRACAO_QUALIDADE_REPROVADA = 0.006  # ~60 em 10.000 (dois sinais simultaneos)
FRACAO_QUALIDADE_LEVE = 0.01  # sinal unico, abaixo do limiar - nao reprova


def _cpf_aleatorio(rng: random.Random) -> str:
    return "".join(rng.choices(string.digits, k=11))


def _documento_aleatorio(rng: random.Random) -> str:
    return "".join(rng.choices(string.ascii_uppercase + string.digits, k=9))


def _gerar_input(rng: random.Random, indice: int) -> OnboardingRiskInput:
    r = rng.random()

    cpf = _cpf_aleatorio(rng)
    documento_numero = _documento_aleatorio(rng)
    nome = "Fulano DaSilva"
    data_nascimento = date(2026, 1, 1) - timedelta(days=rng.randint(18 * 365, 90 * 365))
    ip_origem = f"10.{rng.randint(0, 255)}.{rng.randint(0, 255)}.{rng.randint(0, 255)}"
    dispositivo_id = f"device-{indice}-{rng.randint(0, 999999)}"

    if r < FRACAO_PEP:
        cpf = rng.choice(["11111111111", "22222222222", "33333333333"])
    elif r < FRACAO_PEP + FRACAO_BLACKLIST:
        ip_origem = rng.choice(["198.51.100.66", "203.0.113.66"])
    elif r < FRACAO_PEP + FRACAO_BLACKLIST + FRACAO_QUALIDADE_REPROVADA:
        documento_numero = "!"  # dispara documento_formato_invalido
        nome = "Fulano2"  # dispara dados_inconsistentes -> soma 55 >= 50
    elif r < FRACAO_PEP + FRACAO_BLACKLIST + FRACAO_QUALIDADE_REPROVADA + FRACAO_QUALIDADE_LEVE:
        documento_numero = "!"  # dispara so documento_formato_invalido (30) - abaixo do limiar

    return OnboardingRiskInput(
        cpf=cpf,
        nome=nome,
        data_nascimento=data_nascimento,
        documento_numero=documento_numero,
        ip_origem=ip_origem,
        dispositivo_id=dispositivo_id,
        referencia=date(2026, 1, 1),
    )


def test_reprovacao_combinada_fica_entre_0_5_e_1_porcento_em_amostra_grande() -> None:
    rng = random.Random(SEED)

    reprovados = 0
    aprovados_com_sinal_leve = 0

    for i in range(AMOSTRA):
        risk_input = _gerar_input(rng, i)
        result = evaluate_onboarding_risk(risk_input)

        assert result.status in ("aprovado", "reprovado_qualidade", "reprovado_fraude")
        assert result.score >= 0.0  # score sempre presente, mesmo aprovado

        if result.status in ("reprovado_qualidade", "reprovado_fraude"):
            reprovados += 1
        elif result.sinais:
            aprovados_com_sinal_leve += 1

    percentual_reprovacao = reprovados / AMOSTRA

    assert 0.005 <= percentual_reprovacao <= 0.01, (
        f"reprovacao combinada de {percentual_reprovacao:.4%} fora da faixa [0.5%, 1%] "
        f"({reprovados} de {AMOSTRA})"
    )
    assert aprovados_com_sinal_leve > 0
