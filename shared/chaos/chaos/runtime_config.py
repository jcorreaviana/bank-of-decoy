"""Estado de config de caos ajustavel em runtime (issue #51,
specs/business/24-camada-caos-avancada.md). Em memoria, por processo -
sem persistencia em disco/banco e sem coordenacao entre servicos, mesma
premissa de independencia por servico ja documentada em
chaos/middleware.py (cada servico roda como processo unico por
container, entao uma variavel em memoria do processo e suficiente).

Quando presente, o override de runtime tem prioridade total sobre
CHAOS_ENABLED/CHAOS_FAILURE_RATE/CHAOS_FAILURE_TYPES - que continuam
funcionando como configuracao inicial/fallback (lida em
chaos.middleware._load_config), usada sempre que o endpoint
POST /internal/chaos/config nunca foi chamado ou o override expirou.
"""

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ChaosRuntimeOverride:
    enabled: bool
    failure_rate: float
    failure_types: list[str]
    # Timestamp de `time.monotonic()` em que o override deixa de valer e a
    # config volta a ser lida das variaveis de ambiente. `None` = sem
    # expiracao automatica (vale ate o proximo POST ou restart do processo).
    expires_at: float | None


class _RuntimeConfigStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._override: ChaosRuntimeOverride | None = None

    def set(
        self,
        *,
        enabled: bool,
        failure_rate: float,
        failure_types: list[str],
        duration_seconds: float | None,
    ) -> ChaosRuntimeOverride:
        expires_at = time.monotonic() + duration_seconds if duration_seconds is not None else None
        override = ChaosRuntimeOverride(
            enabled=enabled,
            failure_rate=failure_rate,
            failure_types=list(failure_types),
            expires_at=expires_at,
        )
        with self._lock:
            self._override = override
        return override

    def clear(self) -> None:
        with self._lock:
            self._override = None

    def get(self) -> ChaosRuntimeOverride | None:
        with self._lock:
            override = self._override
            if override is not None and override.expires_at is not None and time.monotonic() >= override.expires_at:
                self._override = None
                return None
            return override


_store = _RuntimeConfigStore()


def set_runtime_override(
    *,
    enabled: bool,
    failure_rate: float,
    failure_types: list[str],
    duration_seconds: float | None,
) -> ChaosRuntimeOverride:
    return _store.set(
        enabled=enabled,
        failure_rate=failure_rate,
        failure_types=failure_types,
        duration_seconds=duration_seconds,
    )


def clear_runtime_override() -> None:
    """Usado pelos testes para isolar o estado global entre casos - nao ha
    endpoint publico equivalente (nao pedido pela spec: a duracao/janela
    e o mecanismo de reversao automatica previsto)."""
    _store.clear()


def get_runtime_override() -> ChaosRuntimeOverride | None:
    return _store.get()
