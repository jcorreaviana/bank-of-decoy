import pytest

from chaos import kafka_chaos
from chaos.runtime_config import ChaosTypeParams, clear_runtime_override, set_runtime_override


def _params(**overrides):
    return ChaosTypeParams(**overrides)


@pytest.fixture(autouse=True)
def _clean_chaos_env(monkeypatch):
    for key in ("CHAOS_ENABLED", "CHAOS_FAILURE_RATE", "CHAOS_FAILURE_TYPES"):
        monkeypatch.delenv(key, raising=False)
    clear_runtime_override()
    yield
    clear_runtime_override()


def test_kafka_lag_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(kafka_chaos.random, "random", lambda: 0.0)
    set_runtime_override(enabled=False, failure_rate=1.0, failure_types=["kafka_lag"], duration_seconds=None)

    assert kafka_chaos.maybe_kafka_lag_delay_seconds() is None


def test_kafka_lag_returns_none_when_type_not_in_active_list(monkeypatch):
    monkeypatch.setattr(kafka_chaos.random, "random", lambda: 0.0)
    set_runtime_override(enabled=True, failure_rate=1.0, failure_types=["503"], duration_seconds=None)

    assert kafka_chaos.maybe_kafka_lag_delay_seconds() is None


def test_kafka_lag_returns_none_when_roll_misses(monkeypatch):
    monkeypatch.setattr(kafka_chaos.random, "random", lambda: 0.99)
    set_runtime_override(enabled=True, failure_rate=0.5, failure_types=["kafka_lag"], duration_seconds=None)

    assert kafka_chaos.maybe_kafka_lag_delay_seconds() is None


def test_kafka_lag_grows_across_successive_affected_messages(monkeypatch):
    monkeypatch.setattr(kafka_chaos.random, "random", lambda: 0.0)
    set_runtime_override(
        enabled=True,
        failure_rate=1.0,
        failure_types=["kafka_lag"],
        duration_seconds=None,
        params=_params(lag_increment_ms=100.0, lag_ceiling_ms=250.0),
    )

    delays_seconds = [kafka_chaos.maybe_kafka_lag_delay_seconds() for _ in range(4)]

    assert delays_seconds == [0.1, 0.2, 0.25, 0.25]


def test_kafka_delay_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(kafka_chaos.random, "random", lambda: 0.0)
    set_runtime_override(enabled=False, failure_rate=1.0, failure_types=["kafka_delay"], duration_seconds=None)

    assert kafka_chaos.maybe_kafka_publish_delay_seconds() is None


def test_kafka_delay_returns_none_when_type_not_in_active_list(monkeypatch):
    monkeypatch.setattr(kafka_chaos.random, "random", lambda: 0.0)
    set_runtime_override(enabled=True, failure_rate=1.0, failure_types=["kafka_lag"], duration_seconds=None)

    assert kafka_chaos.maybe_kafka_publish_delay_seconds() is None


def test_kafka_delay_returns_fixed_configured_delay(monkeypatch):
    monkeypatch.setattr(kafka_chaos.random, "random", lambda: 0.0)
    set_runtime_override(
        enabled=True,
        failure_rate=1.0,
        failure_types=["kafka_delay"],
        duration_seconds=None,
        params=_params(kafka_delay_seconds=2.5),
    )

    assert kafka_chaos.maybe_kafka_publish_delay_seconds() == 2.5
    # Fixo - nao cresce entre chamadas (diferente de kafka_lag).
    assert kafka_chaos.maybe_kafka_publish_delay_seconds() == 2.5
