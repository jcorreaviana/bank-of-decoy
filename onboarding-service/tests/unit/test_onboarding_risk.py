"""Testa so a parte que ainda vive neste servico apos a extracao para
risk_engine (issue #8): as consultas de historico (documento_reciclado,
padrao_mula) e a montagem do OnboardingRiskInput a partir do payload real.
A regra de classificacao em si (pesos, limiares, hard-stop de fraude) e
testada isoladamente em shared/risk_engine/tests/unit/test_onboarding_risk.py
- nao duplicada aqui."""

from datetime import date

from app.schemas.onboarding import OnboardingCreateRequest
from app.services.onboarding_risk import check_documento_reciclado, check_padrao_mula, evaluate_onboarding_risk


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


def test_check_documento_reciclado_caminho_feliz_sem_historico() -> None:
    assert check_documento_reciclado(_FakeDb(), _payload()) is False


def test_check_documento_reciclado_dispara_com_historico() -> None:
    assert check_documento_reciclado(_FakeDbWithMatch(), _payload()) is True


def test_check_padrao_mula_caminho_feliz_sem_historico() -> None:
    assert check_padrao_mula(_FakeDb(), _payload()) is False


def test_check_padrao_mula_dispara_com_historico() -> None:
    assert check_padrao_mula(_FakeDbWithMatch(), _payload()) is True


def test_evaluate_onboarding_risk_aprovado_sem_sinais() -> None:
    result = evaluate_onboarding_risk(_FakeDb(), _payload())

    assert result.status == "aprovado"
    assert result.score == 0.0
    assert result.sinais == []
    assert result.motivo_reprovacao is None


def test_evaluate_onboarding_risk_historico_positivo_vira_reprovado_fraude() -> None:
    # _FakeDbWithMatch responde "achou" para as duas queries (reciclado e
    # mula) - prova que os dois booleanos calculados pela consulta de
    # historico realmente chegam ao motor compartilhado.
    result = evaluate_onboarding_risk(_FakeDbWithMatch(), _payload())

    assert result.status == "reprovado_fraude"
    assert set(result.sinais) == {"documento_reciclado", "padrao_mula"}
    assert result.motivo_reprovacao == "documento_reciclado"


def test_evaluate_onboarding_risk_reprovado_qualidade_via_payload_real() -> None:
    # documento vazio dispara documento_formato_invalido (30) + documento_ilegivel (20) = 50
    result = evaluate_onboarding_risk(_FakeDb(), _payload(documento_numero="   "))

    assert result.status == "reprovado_qualidade"
    assert set(result.sinais) == {"documento_formato_invalido", "documento_ilegivel"}
