"""Testa so a parte que ainda vive neste servico apos a extracao para
risk_engine (issue #8): as consultas de historico (destinatario_novo,
velocidade_alta) e a montagem do TransactionRiskInput a partir do payload
real. A regra de classificacao em si (pesos, limiar, combinacao de sinais)
e testada isoladamente em shared/risk_engine/tests/unit/test_transaction_risk.py
- nao duplicada aqui."""

import uuid
from datetime import datetime, timezone

from app.schemas.transaction import TransactionCreateRequest
from app.services.transaction_risk import (
    check_destinatario_novo,
    check_entrada_saida_rapida,
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
    destinatario_novo (id existente ou None), depois velocidade_alta
    (contagem), depois entrada_saida_rapida (id existente ou None)."""

    def __init__(self, valores: list) -> None:
        self._valores = iter(valores)

    def scalar(self, *_args, **_kwargs):
        return next(self._valores)


def _payload(**overrides) -> TransactionCreateRequest:
    base = {"account_id": uuid.uuid4(), "pix_key_destino": "destino@example.com", "valor": 100.0}
    base.update(overrides)
    return TransactionCreateRequest(**base)


def test_check_destinatario_novo_caminho_feliz_sem_historico() -> None:
    assert check_destinatario_novo(_FakeDbSemHistorico(), uuid.uuid4(), "destino@example.com") is True


def test_check_destinatario_novo_falso_com_historico() -> None:
    assert check_destinatario_novo(_FakeDbComHistoricoDestino(), uuid.uuid4(), "destino@example.com") is False


def test_check_velocidade_alta_caminho_feliz_sem_historico() -> None:
    assert check_velocidade_alta(_FakeDbSemHistorico(), uuid.uuid4(), datetime.now(timezone.utc)) is False


def test_check_velocidade_alta_dispara_com_muitas_transacoes_recentes() -> None:
    assert check_velocidade_alta(_FakeDbComVelocidadeAlta(), uuid.uuid4(), datetime.now(timezone.utc)) is True


def test_check_entrada_saida_rapida_caminho_feliz_sem_entrada_recente() -> None:
    assert check_entrada_saida_rapida(_FakeDbSemHistorico(), uuid.uuid4(), 100.0, datetime.now(timezone.utc)) is False


def test_check_entrada_saida_rapida_dispara_com_entrada_recente_compativel() -> None:
    assert (
        check_entrada_saida_rapida(_FakeDbComHistoricoDestino(), uuid.uuid4(), 100.0, datetime.now(timezone.utc))
        is True
    )


def test_evaluate_transaction_risk_concluida_sem_sinais_suficientes() -> None:
    # destinatario_novo (20) e o unico sinal disparado sem historico - abaixo do limiar
    account_id = uuid.uuid4()
    payload = _payload(valor=100.0)

    result = evaluate_transaction_risk(
        _FakeDbSemHistorico(), payload, account_id, agora=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)
    )

    assert result.status == "concluida"
    assert result.sinais == ["destinatario_novo"]


def test_evaluate_transaction_risk_suspeita_quando_score_atinge_limiar() -> None:
    # valor_atipico (40) + destinatario_novo (20) = 60 >= 50
    account_id = uuid.uuid4()
    payload = _payload(valor=25_000.0)

    result = evaluate_transaction_risk(
        _FakeDbSemHistorico(), payload, account_id, agora=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)
    )

    assert result.status == "suspeita"
    assert set(result.sinais) == {"valor_atipico", "destinatario_novo"}


def test_evaluate_transaction_risk_acumula_todos_os_sinais() -> None:
    account_id = uuid.uuid4()
    payload = _payload(valor=25_000.0)

    # destinatario_novo dispara (None), velocidade_alta dispara (5 >= limiar),
    # entrada_saida_rapida nao dispara (None)
    result = evaluate_transaction_risk(
        _FakeDbSequential([None, 5, None]),
        payload,
        account_id,
        agora=datetime(2026, 1, 1, 3, 30, tzinfo=timezone.utc),
    )

    assert result.status == "suspeita"
    assert set(result.sinais) == {"valor_atipico", "horario_atipico", "destinatario_novo", "velocidade_alta"}


def test_evaluate_transaction_risk_score_sempre_presente_mesmo_concluida() -> None:
    account_id = uuid.uuid4()
    payload = _payload(valor=100.0)

    # destinatario_novo nao dispara (id existente), velocidade_alta nao
    # dispara (0 < limiar), entrada_saida_rapida nao dispara (None)
    result = evaluate_transaction_risk(
        _FakeDbSequential(["00000000-0000-0000-0000-000000000001", 0, None]),
        payload,
        account_id,
        agora=datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc),
    )

    assert result.status == "concluida"
    assert result.score == 0.0
    assert result.sinais == []
