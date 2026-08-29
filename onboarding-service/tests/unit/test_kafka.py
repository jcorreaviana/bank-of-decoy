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
