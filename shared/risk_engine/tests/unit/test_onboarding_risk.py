from datetime import date

from risk_engine.onboarding import (
    LIMIAR_REPROVACAO_QUALIDADE,
    PESO_DADOS_INCONSISTENTES,
    PESO_DOCUMENTO_FORMATO_INVALIDO,
    OnboardingRiskInput,
    RiskResult,
    check_dados_inconsistentes,
    check_documento_formato_invalido,
    check_documento_ilegivel,
    check_ip_dispositivo_blacklist,
    check_pep_detectado,
    evaluate_onboarding_risk,
)


def _input(**overrides) -> OnboardingRiskInput:
    base = dict(
        cpf="12345678901",
        nome="Maria Silva",
        data_nascimento=date(1990, 1, 1),
        documento_numero="AB123456",
        ip_origem="203.0.113.10",
        dispositivo_id="device-1",
        referencia=date(2026, 1, 1),
    )
    base.update(overrides)
    return OnboardingRiskInput(**base)


# --- sinais de qualidade ---


def test_check_documento_formato_invalido_caminho_feliz() -> None:
    assert check_documento_formato_invalido("AB123456") is False


def test_check_documento_formato_invalido_dispara_com_simbolos() -> None:
    assert check_documento_formato_invalido("AB-123!") is True


def test_check_documento_formato_invalido_dispara_com_tamanho_incorreto() -> None:
    assert check_documento_formato_invalido("AB1") is True


def test_check_dados_inconsistentes_caminho_feliz() -> None:
    assert check_dados_inconsistentes("Maria Silva", date(1990, 1, 1), date(2026, 1, 1)) is False


def test_check_dados_inconsistentes_dispara_para_menor_de_idade() -> None:
    assert check_dados_inconsistentes("Maria Silva", date(2015, 6, 1), date(2026, 1, 1)) is True


def test_check_dados_inconsistentes_dispara_para_nome_suspeito() -> None:
    assert check_dados_inconsistentes("Maria2", date(1990, 1, 1), date(2026, 1, 1)) is True


def test_check_documento_ilegivel_caminho_feliz() -> None:
    assert check_documento_ilegivel("AB123456") is False


def test_check_documento_ilegivel_dispara_para_numero_vazio() -> None:
    assert check_documento_ilegivel("   ") is True


# --- sinais de fraude ---


def test_check_pep_detectado_caminho_feliz() -> None:
    assert check_pep_detectado("12345678901") is False


def test_check_pep_detectado_dispara_para_cpf_na_lista() -> None:
    assert check_pep_detectado("11111111111") is True


def test_check_ip_dispositivo_blacklist_caminho_feliz() -> None:
    assert check_ip_dispositivo_blacklist("203.0.113.10", "device-1") is False


def test_check_ip_dispositivo_blacklist_dispara_para_ip_na_lista() -> None:
    assert check_ip_dispositivo_blacklist("198.51.100.66", "device-1") is True


def test_check_ip_dispositivo_blacklist_dispara_para_dispositivo_na_lista() -> None:
    assert check_ip_dispositivo_blacklist("203.0.113.10", "device-blacklist-1") is True


def test_documento_reciclado_dispara_via_flag_precomputada() -> None:
    result = evaluate_onboarding_risk(_input(documento_reciclado=True))
    assert result.status == "reprovado_fraude"
    assert result.sinais == ["documento_reciclado"]


def test_padrao_mula_dispara_via_flag_precomputada() -> None:
    result = evaluate_onboarding_risk(_input(padrao_mula=True))
    assert result.status == "reprovado_fraude"
    assert result.sinais == ["padrao_mula"]


# --- orquestracao: evaluate_onboarding_risk ---


def test_evaluate_onboarding_risk_aprovado_sem_sinais() -> None:
    result = evaluate_onboarding_risk(_input())

    assert result == RiskResult(status="aprovado", score=0.0, sinais=[], motivo_reprovacao=None)


def test_evaluate_onboarding_risk_aprovado_com_score_registrado_abaixo_do_limiar() -> None:
    # dispara apenas dados_inconsistentes (25 pontos) - abaixo do limiar de 50
    result = evaluate_onboarding_risk(_input(nome="Maria2"))

    assert result.status == "aprovado"
    assert result.score == PESO_DADOS_INCONSISTENTES
    assert result.sinais == ["dados_inconsistentes"]
    assert result.motivo_reprovacao is None


def test_evaluate_onboarding_risk_documento_vazio_dispara_formato_e_ilegivel() -> None:
    # numero vazio dispara tanto documento_formato_invalido (30, falha no
    # tamanho minimo) quanto documento_ilegivel (20) - soma 50 atinge o limiar
    result = evaluate_onboarding_risk(_input(documento_numero="   "))

    assert result.status == "reprovado_qualidade"
    assert result.score == LIMIAR_REPROVACAO_QUALIDADE
    assert set(result.sinais) == {"documento_formato_invalido", "documento_ilegivel"}
    assert result.motivo_reprovacao == "documento_formato_invalido"


def test_evaluate_onboarding_risk_reprovado_qualidade_quando_soma_atinge_limiar() -> None:
    # documento_formato_invalido (30) + dados_inconsistentes (25) = 55 >= 50
    result = evaluate_onboarding_risk(_input(documento_numero="!!", nome="Maria2"))

    assert result.status == "reprovado_qualidade"
    assert result.score == PESO_DOCUMENTO_FORMATO_INVALIDO + PESO_DADOS_INCONSISTENTES
    assert result.score >= LIMIAR_REPROVACAO_QUALIDADE
    assert set(result.sinais) == {"documento_formato_invalido", "dados_inconsistentes"}
    assert result.motivo_reprovacao == "documento_formato_invalido"


def test_evaluate_onboarding_risk_reprovado_fraude_tem_prioridade_sobre_qualidade() -> None:
    # payload dispara TODOS os sinais de qualidade (30+25+20=75 >= 50) e um
    # sinal de fraude (pep) simultaneamente - fraude deve vencer.
    result = evaluate_onboarding_risk(
        _input(
            cpf="11111111111",
            documento_numero="   ",
            nome="Maria2",
            data_nascimento=date(2020, 1, 1),
        )
    )

    assert result.status == "reprovado_fraude"
    assert result.score == 100.0
    assert result.sinais == ["pep_detectado"]
    assert result.motivo_reprovacao == "pep_detectado"


def test_evaluate_onboarding_risk_reprovado_fraude_acumula_todos_sinais_de_fraude() -> None:
    result = evaluate_onboarding_risk(_input(cpf="11111111111", ip_origem="198.51.100.66"))

    assert result.status == "reprovado_fraude"
    assert result.score == 100.0
    assert set(result.sinais) == {"pep_detectado", "ip_dispositivo_blacklist"}
