import uuid
from datetime import datetime, timezone

from app.schemas.transaction import TransactionCreateRequest
from app.services.transaction_risk import (
    LIMIAR_SUSPEITA,
    PESO_DESTINATARIO_NOVO,
    PESO_HORARIO_ATIPICO,
    PESO_VALOR_ATIPICO,
    PESO_VELOCIDADE_ALTA,
    RiskResult,
    check_destinatario_novo,
    check_horario_atipico,
    check_valor_atipico,
    check_velocidade_alta,
    evaluate_transaction_risk,
)


class _FakeDbSemHistorico:
    """Duplo de teste para Session: nunca encontra historico (destinatario
    sempre novo, velocidade sempre baixa), sem depender de banco real."""

    def scalar(self, *_args, **_kwargs):
        return None


class _FakeDbComHistoricoDestino:
    def scalar(self, *_args, **_kwargs):
        return "00000000-0000-0000-0000-000000000001"


class _FakeDbComVelocidadeAlta:
    def scalar(self, *_args, **_kwargs):
        return 5


class _FakeDbSequential:
    """Duplo de Session cujo `scalar` retorna, em ordem, os valores dados.

    A ordem de chamadas de `evaluate_transaction_risk` e sempre:
    destinatario_novo (id existente ou None) e depois velocidade_alta
    (contagem) - permite simular as duas checagens de historico
    simultaneamente com respostas distintas e coerentes com o tipo
    esperado por cada query (diferente de usar o mesmo valor para as duas,
    que quebraria a comparacao numerica de velocidade_alta)."""

    def __init__(self, valores: list) -> None:
        self._valores = iter(valores)

    def scalar(self, *_args, **_kwargs):
        return next(self._valores)


def _payload(**overrides) -> TransactionCreateRequest:
    base = {"account_id": uuid.uuid4(), "pix_key_destino": "destino@example.com", "valor": 100.0}
    base.update(overrides)
    return TransactionCreateRequest(**base)


# --- sinais individuais ---


def test_check_valor_atipico_caminho_feliz() -> None:
    assert check_valor_atipico(_payload(valor=100.0)) is False


def test_check_valor_atipico_dispara_acima_do_limiar() -> None:
    assert check_valor_atipico(_payload(valor=20_000.01)) is True


def test_check_horario_atipico_caminho_feliz() -> None:
    assert check_horario_atipico(datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)) is False


def test_check_horario_atipico_dispara_na_madrugada() -> None:
    assert check_horario_atipico(datetime(2026, 1, 1, 3, 30, tzinfo=timezone.utc)) is True


def test_check_destinatario_novo_caminho_feliz_sem_historico() -> None:
    assert check_destinatario_novo(_FakeDbSemHistorico(), uuid.uuid4(), "destino@example.com") is True


def test_check_destinatario_novo_falso_com_historico() -> None:
    assert check_destinatario_novo(_FakeDbComHistoricoDestino(), uuid.uuid4(), "destino@example.com") is False


def test_check_velocidade_alta_caminho_feliz_sem_historico() -> None:
    assert check_velocidade_alta(_FakeDbSemHistorico(), uuid.uuid4(), datetime.now(timezone.utc)) is False


def test_check_velocidade_alta_dispara_com_muitas_transacoes_recentes() -> None:
    assert check_velocidade_alta(_FakeDbComVelocidadeAlta(), uuid.uuid4(), datetime.now(timezone.utc)) is True


# --- orquestracao: evaluate_transaction_risk ---


def test_evaluate_transaction_risk_concluida_sem_sinais_suficientes() -> None:
    # destinatario_novo (20) e o unico sinal disparado sem historico - abaixo do limiar
    account_id = uuid.uuid4()
    payload = _payload(valor=100.0)

    result = evaluate_transaction_risk(
        _FakeDbSemHistorico(), payload, account_id, agora=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)
    )

    assert result == RiskResult(status="concluida", score=PESO_DESTINATARIO_NOVO, sinais=["destinatario_novo"])


def test_evaluate_transaction_risk_suspeita_quando_score_atinge_limiar() -> None:
    # valor_atipico (40) + destinatario_novo (20) = 60 >= 50
    account_id = uuid.uuid4()
    payload = _payload(valor=25_000.0)

    result = evaluate_transaction_risk(
        _FakeDbSemHistorico(), payload, account_id, agora=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)
    )

    assert result.status == "suspeita"
    assert result.score == PESO_VALOR_ATIPICO + PESO_DESTINATARIO_NOVO
    assert set(result.sinais) == {"valor_atipico", "destinatario_novo"}


def test_evaluate_transaction_risk_acumula_todos_os_sinais() -> None:
    account_id = uuid.uuid4()
    payload = _payload(valor=25_000.0)

    # destinatario_novo dispara (None) e velocidade_alta dispara (5 >= limiar)
    result = evaluate_transaction_risk(
        _FakeDbSequential([None, 5]),
        payload,
        account_id,
        agora=datetime(2026, 1, 1, 3, 30, tzinfo=timezone.utc),
    )

    assert result.status == "suspeita"
    assert result.score == PESO_VALOR_ATIPICO + PESO_HORARIO_ATIPICO + PESO_DESTINATARIO_NOVO + PESO_VELOCIDADE_ALTA
    assert set(result.sinais) == {"valor_atipico", "horario_atipico", "destinatario_novo", "velocidade_alta"}


def test_evaluate_transaction_risk_score_sempre_presente_mesmo_concluida() -> None:
    account_id = uuid.uuid4()
    payload = _payload(valor=100.0)

    # destinatario_novo nao dispara (id existente) e velocidade_alta nao dispara (0 < limiar)
    result = evaluate_transaction_risk(
        _FakeDbSequential(["00000000-0000-0000-0000-000000000001", 0]),
        payload,
        account_id,
        agora=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc),
    )

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
