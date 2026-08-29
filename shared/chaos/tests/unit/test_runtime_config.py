import pytest

from chaos import runtime_config
from chaos.runtime_config import clear_runtime_override, get_runtime_override, set_runtime_override


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
