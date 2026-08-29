import pytest

from chaos import runtime_config
from chaos.runtime_config import (
    ChaosTypeParams,
    clear_runtime_override,
    get_active_type_params,
    get_activation_time,
    get_runtime_override,
    record_kafka_lag_message,
    set_runtime_override,
)


@pytest.fixture(autouse=True)
def _clean_runtime_override():
    clear_runtime_override()
    yield
    clear_runtime_override()


def test_get_returns_none_when_never_set():
    assert get_runtime_override() is None


def test_set_then_get_returns_the_override():
    override = set_runtime_override(enabled=True, failure_rate=0.9, failure_types=["503"], duration_seconds=None)

    assert get_runtime_override() == override
    assert override.enabled is True
    assert override.failure_rate == 0.9
    assert override.failure_types == ["503"]
    assert override.expires_at is None


def test_clear_removes_the_override():
    set_runtime_override(enabled=True, failure_rate=0.9, failure_types=["503"], duration_seconds=None)

    clear_runtime_override()

    assert get_runtime_override() is None


def test_set_without_duration_never_expires(monkeypatch):
    monkeypatch.setattr(runtime_config.time, "monotonic", lambda: 1000.0)
    set_runtime_override(enabled=True, failure_rate=1.0, failure_types=["500"], duration_seconds=None)

    monkeypatch.setattr(runtime_config.time, "monotonic", lambda: 1_000_000.0)

    assert get_runtime_override() is not None


def test_override_expires_after_duration_elapses(monkeypatch):
    monkeypatch.setattr(runtime_config.time, "monotonic", lambda: 1000.0)
    set_runtime_override(enabled=True, failure_rate=1.0, failure_types=["500"], duration_seconds=60.0)

    monkeypatch.setattr(runtime_config.time, "monotonic", lambda: 1000.0 + 59.0)
    assert get_runtime_override() is not None

    monkeypatch.setattr(runtime_config.time, "monotonic", lambda: 1000.0 + 60.0)
    assert get_runtime_override() is None


def test_expired_override_is_cleared_not_just_hidden(monkeypatch):
    """Uma vez expirado, o override some de vez do store (nao so fica
    escondido) - proxima leitura nao paga o custo de checar expiracao de
    novo, e o estado nao "ressuscita" se o relogio monotonic for lido de
    forma inconsistente em algum caminho de teste."""
    monkeypatch.setattr(runtime_config.time, "monotonic", lambda: 1000.0)
    set_runtime_override(enabled=True, failure_rate=1.0, failure_types=["500"], duration_seconds=10.0)

    monkeypatch.setattr(runtime_config.time, "monotonic", lambda: 1020.0)
    assert get_runtime_override() is None

    store = runtime_config._store
    assert store._override is None


def test_get_active_type_params_defaults_when_no_override():
    params = get_active_type_params()

    assert params == ChaosTypeParams()


def test_get_active_type_params_returns_override_params():
    custom = ChaosTypeParams(
        ramp_ceiling_seconds=5.0,
        ramp_window_seconds=60.0,
        lag_increment_ms=100.0,
        lag_ceiling_ms=2000.0,
        kafka_delay_seconds=1.5,
    )
    set_runtime_override(enabled=True, failure_rate=1.0, failure_types=["degradacao_progressiva"], duration_seconds=None, params=custom)

    assert get_active_type_params() == custom


def test_activation_time_defaults_to_process_start_when_no_override(monkeypatch):
    monkeypatch.setattr(runtime_config, "_PROCESS_START", 42.0)

    assert get_activation_time() == 42.0


def test_activation_time_is_set_at_the_moment_of_the_post(monkeypatch):
    monkeypatch.setattr(runtime_config.time, "monotonic", lambda: 500.0)

    set_runtime_override(enabled=True, failure_rate=1.0, failure_types=["degradacao_progressiva"], duration_seconds=None)

    assert get_activation_time() == 500.0


def test_activation_time_resets_on_every_post(monkeypatch):
    """Decisao confirmada com o usuario: cada POST e um experimento novo -
    reconfigurar reinicia a referencia da rampa, mesmo sem desativar o
    tipo entre uma chamada e outra."""
    monkeypatch.setattr(runtime_config.time, "monotonic", lambda: 500.0)
    set_runtime_override(enabled=True, failure_rate=1.0, failure_types=["degradacao_progressiva"], duration_seconds=None)
    assert get_activation_time() == 500.0

    monkeypatch.setattr(runtime_config.time, "monotonic", lambda: 900.0)
    set_runtime_override(enabled=True, failure_rate=1.0, failure_types=["degradacao_progressiva"], duration_seconds=None)

    assert get_activation_time() == 900.0


def test_record_kafka_lag_message_grows_and_caps_at_ceiling():
    set_runtime_override(enabled=True, failure_rate=1.0, failure_types=["kafka_lag"], duration_seconds=None)

    delays = [record_kafka_lag_message(increment_ms=100.0, ceiling_ms=250.0) for _ in range(5)]

    assert delays == [100.0, 200.0, 250.0, 250.0, 250.0]


def test_kafka_lag_counter_resets_on_every_post():
    set_runtime_override(enabled=True, failure_rate=1.0, failure_types=["kafka_lag"], duration_seconds=None)
    record_kafka_lag_message(increment_ms=100.0, ceiling_ms=1000.0)
    record_kafka_lag_message(increment_ms=100.0, ceiling_ms=1000.0)

    # Reconfigurar (mesmo so repetindo os mesmos parametros) e um
    # experimento novo - o contador volta a zero.
    set_runtime_override(enabled=True, failure_rate=1.0, failure_types=["kafka_lag"], duration_seconds=None)

    assert record_kafka_lag_message(increment_ms=100.0, ceiling_ms=1000.0) == 100.0
