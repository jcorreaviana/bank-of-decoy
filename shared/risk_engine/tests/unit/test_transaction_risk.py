from risk_engine.transaction import (
    LIMIAR_SUSPEITA,
    PESO_DESTINATARIO_NOVO,
    PESO_ENTRADA_SAIDA_RAPIDA,
    PESO_HORARIO_ATIPICO,
    PESO_VALOR_ATIPICO,
    PESO_VELOCIDADE_ALTA,
    RiskResult,
    TransactionRiskInput,
    check_horario_atipico,
    check_valor_atipico,
    evaluate_transaction_risk,
)


def _input(**overrides) -> TransactionRiskInput:
    base = dict(valor=100.0, hora=14)
    base.update(overrides)
    return TransactionRiskInput(**base)


# --- sinais individuais ---


def test_check_valor_atipico_caminho_feliz() -> None:
    assert check_valor_atipico(100.0) is False


def test_check_valor_atipico_dispara_acima_do_limiar() -> None:
    assert check_valor_atipico(20_000.01) is True


def test_check_horario_atipico_caminho_feliz() -> None:
    assert check_horario_atipico(14) is False


def test_check_horario_atipico_dispara_na_madrugada() -> None:
    assert check_horario_atipico(3) is True


def test_destinatario_novo_dispara_via_flag_precomputada() -> None:
    result = evaluate_transaction_risk(_input(destinatario_novo=True))
    assert result.sinais == ["destinatario_novo"]
    assert result.score == PESO_DESTINATARIO_NOVO


def test_velocidade_alta_dispara_via_flag_precomputada() -> None:
    result = evaluate_transaction_risk(_input(velocidade_alta=True))
    assert result.sinais == ["velocidade_alta"]
    assert result.score == PESO_VELOCIDADE_ALTA


def test_entrada_saida_rapida_dispara_via_flag_precomputada() -> None:
    result = evaluate_transaction_risk(_input(entrada_saida_rapida=True))
    assert result.sinais == ["entrada_saida_rapida"]
    assert result.score == PESO_ENTRADA_SAIDA_RAPIDA


# --- orquestracao: evaluate_transaction_risk ---


def test_evaluate_transaction_risk_concluida_sem_sinais_suficientes() -> None:
    # destinatario_novo (20) e o unico sinal disparado - abaixo do limiar
    result = evaluate_transaction_risk(_input(destinatario_novo=True))

    assert result == RiskResult(status="concluida", score=PESO_DESTINATARIO_NOVO, sinais=["destinatario_novo"])


def test_evaluate_transaction_risk_suspeita_quando_score_atinge_limiar() -> None:
    # valor_atipico (40) + destinatario_novo (20) = 60 >= 50
    result = evaluate_transaction_risk(_input(valor=25_000.0, destinatario_novo=True))

    assert result.status == "suspeita"
    assert result.score == PESO_VALOR_ATIPICO + PESO_DESTINATARIO_NOVO
    assert set(result.sinais) == {"valor_atipico", "destinatario_novo"}


def test_evaluate_transaction_risk_acumula_todos_os_sinais() -> None:
    result = evaluate_transaction_risk(
        _input(valor=25_000.0, hora=3, destinatario_novo=True, velocidade_alta=True)
    )

    assert result.status == "suspeita"
    assert result.score == PESO_VALOR_ATIPICO + PESO_HORARIO_ATIPICO + PESO_DESTINATARIO_NOVO + PESO_VELOCIDADE_ALTA
    assert set(result.sinais) == {"valor_atipico", "horario_atipico", "destinatario_novo", "velocidade_alta"}


def test_evaluate_transaction_risk_score_sempre_presente_mesmo_concluida() -> None:
    result = evaluate_transaction_risk(_input())

    assert result == RiskResult(status="concluida", score=0.0, sinais=[])


def test_limiar_suspeita_e_atingivel_por_pelo_menos_duas_combinacoes() -> None:
    # documenta a intencao de design: nenhum sinal isolado basta, mas ao
    # menos duas combinacoes plausiveis (mula: velocidade+destinatario;
    # valor alto fora de hora: valor+horario) cruzam o limiar.
    assert PESO_VELOCIDADE_ALTA + PESO_DESTINATARIO_NOVO >= LIMIAR_SUSPEITA
    assert PESO_VALOR_ATIPICO + PESO_HORARIO_ATIPICO >= LIMIAR_SUSPEITA
    assert PESO_VALOR_ATIPICO < LIMIAR_SUSPEITA
    assert PESO_HORARIO_ATIPICO < LIMIAR_SUSPEITA
    assert PESO_DESTINATARIO_NOVO < LIMIAR_SUSPEITA
    assert PESO_VELOCIDADE_ALTA < LIMIAR_SUSPEITA
    assert PESO_ENTRADA_SAIDA_RAPIDA < LIMIAR_SUSPEITA
