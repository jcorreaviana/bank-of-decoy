from unittest.mock import MagicMock, patch

import pytest
from chaos import kafka_chaos
from chaos.runtime_config import ChaosTypeParams, clear_runtime_override, set_runtime_override

from app.core import kafka


@pytest.fixture(autouse=True)
def _clean_chaos_runtime_override():
    clear_runtime_override()
    yield
    clear_runtime_override()


def test_publish_event_applies_kafka_delay_before_producing(monkeypatch):
    """kafka_delay real (issue #52, specs/business/24-camada-caos-avancada.md)
    - a decisao de caos (chaos/kafka_chaos.py) NAO e mockada aqui, so o
    Producer confluent-kafka (get_producer) e time.sleep (para o teste
    nao esperar de verdade)."""
    set_runtime_override(
        enabled=True,
        failure_rate=1.0,
        failure_types=["kafka_delay"],
        duration_seconds=None,
        params=ChaosTypeParams(kafka_delay_seconds=2.5),
    )
    monkeypatch.setattr(kafka_chaos.random, "random", lambda: 0.0)

    producer = MagicMock()
    producer.flush.return_value = 0
    sleep_calls: list[float] = []
    monkeypatch.setattr(kafka.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    with patch("app.core.kafka.get_producer", return_value=producer):
        kafka.publish_event("onboarding.aprovado", {"event_id": "e1"})

    assert sleep_calls == [2.5]
    producer.produce.assert_called_once()
    producer.flush.assert_called_once()


def test_publish_event_does_not_delay_when_kafka_delay_not_active(monkeypatch):
    producer = MagicMock()
    producer.flush.return_value = 0
    sleep_calls: list[float] = []
    monkeypatch.setattr(kafka.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    with patch("app.core.kafka.get_producer", return_value=producer):
        kafka.publish_event("onboarding.aprovado", {"event_id": "e1"})

    assert sleep_calls == []
    producer.produce.assert_called_once()


def test_publish_event_does_not_delay_when_disabled(monkeypatch):
    set_runtime_override(enabled=False, failure_rate=1.0, failure_types=["kafka_delay"], duration_seconds=None)
    monkeypatch.setattr(kafka_chaos.random, "random", lambda: 0.0)

    producer = MagicMock()
    producer.flush.return_value = 0
    sleep_calls: list[float] = []
    monkeypatch.setattr(kafka.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    with patch("app.core.kafka.get_producer", return_value=producer):
        kafka.publish_event("onboarding.aprovado", {"event_id": "e1"})

    assert sleep_calls == []


def test_publish_events_produces_todas_as_mensagens_com_um_unico_flush(monkeypatch):
    """Issue #69: dois eventos do mesmo fato de negocio (ex. onboarding
    reprovado, resultado + fila de revisao) nao podem gerar dois flushes
    sequenciais - cada flush bloqueia ate a confirmacao de entrega, entao
    dois flushes em serie dobravam o tempo do request nesse caminho."""
    producer = MagicMock()
    producer.flush.return_value = 0

    with patch("app.core.kafka.get_producer", return_value=producer):
        kafka.publish_events(
            [
                ("onboarding.reprovado_qualidade", {"event_id": "e1"}, "chave-1"),
                ("onboarding.revisao_qualidade", {"event_id": "e1"}, "chave-1"),
            ]
        )

    assert producer.produce.call_count == 2
    producer.flush.assert_called_once()


def test_publish_events_sem_eventos_nao_produz_nem_flusha():
    producer = MagicMock()

    with patch("app.core.kafka.get_producer", return_value=producer):
        kafka.publish_events([])

    producer.produce.assert_not_called()
    producer.flush.assert_not_called()


def test_delivery_callback_loga_key_em_caso_de_falha(caplog):
    """Issue #99: sem a key (onboarding_id usado como chave de particionamento,
    ver onboarding_events.py) no log de falha de entrega, e impossivel saber
    qual onboarding especifico teve o evento nao entregue so pelo log."""
    msg = MagicMock()
    msg.topic.return_value = "onboarding.aprovado"
    msg.key.return_value = b"onboarding-123"

    with caplog.at_level("ERROR"):
        kafka._delivery_callback("erro simulado", msg)

    assert len(caplog.records) == 1
    assert caplog.records[0].context["key"] == "onboarding-123"
