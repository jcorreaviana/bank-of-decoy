"""Valida a distribuicao gerada em uma amostra menor (10.000 onboardings)
antes de rodar a carga completa de 500k+ (specs/business/08-populador-volume.md,
criterio de aceite: "teste automatizado valida a distribuicao... em uma
amostra menor... para detectar regressao de proporcao sem esperar a
execucao completa"). Nao toca banco - so exercita generation.py.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import random

from generation import gerar_conta_e_pix_key, gerar_onboarding, gerar_transacoes
from risk_engine.onboarding import CPFS_PEP_SIMULADOS

AMOSTRA = 10_000
SEED = 20260826
# fixo no import do modulo (nao a cada chamada) - _rodar_amostra congela o
# momento de transacoes tardias em `agora` (generation.gerar_transacoes,
# `min(momento + incremento, agora)`), e esse momento congelado alimenta o
# sinal de risco horario_atipico (hora == 3). Se cada chamada capturasse seu
# proprio datetime.now(), duas chamadas com a MESMA seed veriam `agora`
# diferentes - e mesma seed deveria bastar para determinismo, sem depender
# de quando no relogio de parede o teste rodou.
AGORA = datetime.now(timezone.utc)


def _rodar_amostra(seed: int, amostra: int = AMOSTRA):
    rng = random.Random(seed)
    agora = AGORA

    reprovados = 0
    contas = 0
    transacoes = 0
    suspeitas = 0
    cpfs_vistos = set()
    onboarding_ids_vistos = set()
    pix_key_valores_vistos = set()

    for indice in range(amostra):
        onboarding = gerar_onboarding(rng, indice, agora)

        assert onboarding.cpf not in cpfs_vistos, "cpf duplicado - violaria cpf_hash unico no banco real"
        cpfs_vistos.add(onboarding.cpf)
        assert onboarding.id not in onboarding_ids_vistos
        onboarding_ids_vistos.add(onboarding.id)

        if onboarding.status in ("reprovado_qualidade", "reprovado_fraude"):
            reprovados += 1
            continue

        account, pix_key = gerar_conta_e_pix_key(rng, indice, onboarding)
        assert pix_key.valor not in pix_key_valores_vistos, "valor de pix key duplicado - violaria unique no banco real"
        pix_key_valores_vistos.add(pix_key.valor)
        contas += 1

        n_transacoes_conta = 0
        for transacao in gerar_transacoes(rng, account, agora):
            transacoes += 1
            n_transacoes_conta += 1
            if transacao.status == "suspeita":
                suspeitas += 1

        assert 20 <= n_transacoes_conta <= 50

    return {
        "reprovados": reprovados,
        "contas": contas,
        "transacoes": transacoes,
        "suspeitas": suspeitas,
        "percentual_reprovacao": reprovados / amostra,
        "percentual_suspeita": suspeitas / transacoes if transacoes else 0.0,
    }


def test_percentual_reprovacao_onboarding_fica_entre_0_5_e_1_porcento() -> None:
    resultado = _rodar_amostra(SEED)

    assert 0.005 <= resultado["percentual_reprovacao"] <= 0.01, (
        f"reprovacao de {resultado['percentual_reprovacao']:.4%} fora de [0.5%, 1%]"
    )


def test_percentual_suspeita_transacao_fica_entre_1_e_2_porcento() -> None:
    resultado = _rodar_amostra(SEED)

    assert 0.01 <= resultado["percentual_suspeita"] <= 0.02, (
        f"suspeita de {resultado['percentual_suspeita']:.4%} fora de [1%, 2%]"
    )


def test_cada_conta_tem_entre_20_e_50_transacoes() -> None:
    resultado = _rodar_amostra(SEED)

    media = resultado["transacoes"] / resultado["contas"]
    assert 20 <= media <= 50


def test_mesma_seed_produz_a_mesma_distribuicao() -> None:
    resultado1 = _rodar_amostra(SEED)
    resultado2 = _rodar_amostra(SEED)

    assert resultado1 == resultado2


def test_seed_diferente_produz_distribuicao_diferente() -> None:
    resultado_seed_original = _rodar_amostra(SEED)
    resultado_seed_alternativa = _rodar_amostra(SEED + 1)

    # nao exige que o PERCENTUAL mude (ambos devem ficar dentro da faixa
    # calibrada), mas os totais absolutos de reprovados/suspeitas -
    # dependentes da sequencia pseudoaleatoria - devem divergir; senao a
    # seed nao estaria de fato controlando nada.
    assert resultado_seed_original["reprovados"] != resultado_seed_alternativa["reprovados"] or (
        resultado_seed_original["suspeitas"] != resultado_seed_alternativa["suspeitas"]
    )


def test_nenhum_cpf_sintetico_parece_um_cpf_real_conhecido() -> None:
    # specs/tech/testing.md: "sem uso de CPF... reais em fixtures" - os
    # CPFs sinteticos usam um prefixo fixo (10_000_000_000+indice), exceto
    # os 3 indices reservados para os CPFs de PEP simulados
    # (risk_engine.onboarding.CPFS_PEP_SIMULADOS - tambem obviamente
    # sinteticos, ja documentados como simulados no proprio motor de risco).
    rng = random.Random(SEED)
    agora = datetime.now(timezone.utc)
    amostra = [gerar_onboarding(rng, i, agora) for i in range(100)]

    for indice, onboarding in enumerate(amostra):
        assert len(onboarding.cpf) == 11
        assert onboarding.cpf.isdigit()
        if indice >= len(CPFS_PEP_SIMULADOS):
            assert onboarding.cpf.startswith("1")
