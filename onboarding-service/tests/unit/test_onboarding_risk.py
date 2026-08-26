from datetime import date

from app.schemas.onboarding import OnboardingCreateRequest
from app.services.onboarding_risk import (
    LIMIAR_REPROVACAO_QUALIDADE,
    PESO_DADOS_INCONSISTENTES,
    PESO_DOCUMENTO_FORMATO_INVALIDO,
    RiskResult,
    check_dados_inconsistentes,
    check_documento_formato_invalido,
    check_documento_ilegivel,
    check_documento_reciclado,
    check_ip_dispositivo_blacklist,
    check_padrao_mula,
    check_pep_detectado,
    evaluate_onboarding_risk,
)


class _FakeDb:
    """Duplo de teste para Session: nunca encontra historico (reciclado/mula
    nunca disparam), sem depender de banco real."""

    def scalar(self, *_args, **_kwargs):
        return None


class _FakeDbWithMatch:
    """Duplo de teste que sempre encontra um registro correspondente."""

    def scalar(self, *_args, **_kwargs):
        return "00000000-0000-0000-0000-000000000001"


def _payload(**overrides) -> OnboardingCreateRequest:
    base = {
        "cpf": "12345678901",
        "nome": "Maria Silva",
        "data_nascimento": date(1990, 1, 1),
        "email": "maria@example.com",
        "telefone": "11999999999",
        "documento_tipo": "rg",
        "documento_numero": "AB123456",
        "dispositivo_id": "device-1",
        "ip_origem": "203.0.113.10",
    }
    base.update(overrides)
    return OnboardingCreateRequest(**base)


# --- sinais de qualidade ---


def test_check_documento_formato_invalido_caminho_feliz() -> None:
    assert check_documento_formato_invalido(_payload(documento_numero="AB123456")) is False


def test_check_documento_formato_invalido_dispara_com_simbolos() -> None:
    assert check_documento_formato_invalido(_payload(documento_numero="AB-123!")) is True


def test_check_documento_formato_invalido_dispara_com_tamanho_incorreto() -> None:
    assert check_documento_formato_invalido(_payload(documento_numero="AB1")) is True


def test_check_dados_inconsistentes_caminho_feliz() -> None:
    assert check_dados_inconsistentes(_payload(data_nascimento=date(1990, 1, 1), nome="Maria Silva")) is False


def test_check_dados_inconsistentes_dispara_para_menor_de_idade() -> None:
    hoje = date(2026, 1, 1)
    payload = _payload(data_nascimento=date(2015, 6, 1))
    assert check_dados_inconsistentes(payload, hoje=hoje) is True


def test_check_dados_inconsistentes_dispara_para_nome_suspeito() -> None:
    assert check_dados_inconsistentes(_payload(nome="Maria2")) is True


def test_check_documento_ilegivel_caminho_feliz() -> None:
    assert check_documento_ilegivel(_payload(documento_numero="AB123456")) is False


def test_check_documento_ilegivel_dispara_para_numero_vazio() -> None:
    assert check_documento_ilegivel(_payload(documento_numero="   ")) is True


# --- sinais de fraude ---


def test_check_pep_detectado_caminho_feliz() -> None:
    assert check_pep_detectado(_payload(cpf="12345678901")) is False


def test_check_pep_detectado_dispara_para_cpf_na_lista() -> None:
    assert check_pep_detectado(_payload(cpf="11111111111")) is True


def test_check_ip_dispositivo_blacklist_caminho_feliz() -> None:
    assert check_ip_dispositivo_blacklist(_payload(ip_origem="203.0.113.10", dispositivo_id="device-1")) is False


def test_check_ip_dispositivo_blacklist_dispara_para_ip_na_lista() -> None:
    assert check_ip_dispositivo_blacklist(_payload(ip_origem="198.51.100.66")) is True


def test_check_ip_dispositivo_blacklist_dispara_para_dispositivo_na_lista() -> None:
    assert check_ip_dispositivo_blacklist(_payload(dispositivo_id="device-blacklist-1")) is True


def test_check_documento_reciclado_caminho_feliz_sem_historico() -> None:
    assert check_documento_reciclado(_FakeDb(), _payload()) is False


def test_check_documento_reciclado_dispara_com_historico() -> None:
    assert check_documento_reciclado(_FakeDbWithMatch(), _payload()) is True


def test_check_padrao_mula_caminho_feliz_sem_historico() -> None:
    assert check_padrao_mula(_FakeDb(), _payload()) is False


def test_check_padrao_mula_dispara_com_historico() -> None:
    assert check_padrao_mula(_FakeDbWithMatch(), _payload()) is True


# --- orquestracao: evaluate_onboarding_risk ---


def test_evaluate_onboarding_risk_aprovado_sem_sinais() -> None:
    result = evaluate_onboarding_risk(_FakeDb(), _payload())

    assert result == RiskResult(status="aprovado", score=0.0, sinais=[], motivo_reprovacao=None)


def test_evaluate_onboarding_risk_aprovado_com_score_registrado_abaixo_do_limiar() -> None:
    # dispara apenas dados_inconsistentes (25 pontos) - abaixo do limiar de 50
    payload = _payload(nome="Maria2")

    result = evaluate_onboarding_risk(_FakeDb(), payload)

    assert result.status == "aprovado"
    assert result.score == PESO_DADOS_INCONSISTENTES
    assert result.sinais == ["dados_inconsistentes"]
    assert result.motivo_reprovacao is None


def test_evaluate_onboarding_risk_documento_vazio_dispara_formato_e_ilegivel() -> None:
    # numero vazio dispara tanto documento_formato_invalido (30, falha no
    # tamanho minimo) quanto documento_ilegivel (20) - soma 50 atinge o limiar
    payload = _payload(documento_numero="   ")

    result = evaluate_onboarding_risk(_FakeDb(), payload)

    assert result.status == "reprovado_qualidade"
    assert result.score == LIMIAR_REPROVACAO_QUALIDADE
    assert set(result.sinais) == {"documento_formato_invalido", "documento_ilegivel"}
    assert result.motivo_reprovacao == "documento_formato_invalido"


def test_evaluate_onboarding_risk_reprovado_qualidade_quando_soma_atinge_limiar() -> None:
    # documento_formato_invalido (30) + dados_inconsistentes (25) = 55 >= 50
    payload = _payload(documento_numero="!!", nome="Maria2")

    result = evaluate_onboarding_risk(_FakeDb(), payload)

    assert result.status == "reprovado_qualidade"
    assert result.score == PESO_DOCUMENTO_FORMATO_INVALIDO + PESO_DADOS_INCONSISTENTES
    assert result.score >= LIMIAR_REPROVACAO_QUALIDADE
    assert set(result.sinais) == {"documento_formato_invalido", "dados_inconsistentes"}
    assert result.motivo_reprovacao == "documento_formato_invalido"


def test_evaluate_onboarding_risk_reprovado_fraude_tem_prioridade_sobre_qualidade() -> None:
    # payload dispara TODOS os sinais de qualidade (30+25+20=75 >= 50) e um
    # sinal de fraude (pep) simultaneamente - fraude deve vencer.
    payload = _payload(
        cpf="11111111111",
        documento_numero="   ",
        nome="Maria2",
        data_nascimento=date(2020, 1, 1),
    )

    result = evaluate_onboarding_risk(_FakeDb(), payload)

    assert result.status == "reprovado_fraude"
    assert result.score == 100.0
    assert result.sinais == ["pep_detectado"]
    assert result.motivo_reprovacao == "pep_detectado"


def test_evaluate_onboarding_risk_reprovado_fraude_acumula_todos_sinais_de_fraude() -> None:
    payload = _payload(cpf="11111111111", ip_origem="198.51.100.66")

    result = evaluate_onboarding_risk(_FakeDb(), payload)

    assert result.status == "reprovado_fraude"
    assert result.score == 100.0
    assert set(result.sinais) == {"pep_detectado", "ip_dispositivo_blacklist"}
