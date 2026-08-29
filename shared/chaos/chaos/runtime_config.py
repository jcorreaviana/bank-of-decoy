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

Desde a issue #52, tambem guarda os parametros especificos dos 4 novos
tipos de falha (ChaosTypeParams) e o estado mutavel de progressao
(rampa de `degradacao_progressiva`, contador de `kafka_lag`) - ambos
resetados a cada POST /internal/chaos/config, por decisao confirmada
com o usuario: cada chamada ao endpoint e um novo "experimento", nao
uma continuacao do anterior.
"""

import threading
import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChaosTypeParams:
    """Parametros especificos dos tipos de falha da Fase 2b. Todos tem
    default (mesmo padrao das constantes fixas _TIMEOUT_DELAY_SECONDS/
    _LATENCY_DELAY_SECONDS em chaos/middleware.py para os tipos da Fase
    2) - so passam a ser ajustaveis de fato quando definidos via
    POST /internal/chaos/config; nao ha variavel de ambiente equivalente
    para eles, sao novos demais para reaproveitar CHAOS_* existentes."""

    # degradacao_progressiva: rampa de 0 ate ramp_ceiling_seconds, ao
    # longo de ramp_window_seconds desde a ativacao (ver activated_at).
    ramp_ceiling_seconds: float = 3.0
    ramp_window_seconds: float = 300.0

    # kafka_lag: incremento por mensagem afetada, ate o teto.
    lag_increment_ms: float = 200.0
    lag_ceiling_ms: float = 5000.0

    # kafka_delay: atraso fixo antes do publish.
    kafka_delay_seconds: float = 3.0


@dataclass(frozen=True)
class ChaosRuntimeOverride:
    enabled: bool
    failure_rate: float
    failure_types: list[str]
    # Timestamp de `time.monotonic()` em que o override deixa de valer e a
    # config volta a ser lida das variaveis de ambiente. `None` = sem
    # expiracao automatica (vale ate o proximo POST ou restart do processo).
    expires_at: float | None
    params: ChaosTypeParams = field(default_factory=ChaosTypeParams)
    # Momento (time.monotonic()) em que ESTE override foi criado - usado
    # como referencia da rampa de degradacao_progressiva. Cada POST cria
    # um override novo, entao a rampa reinicia a cada reconfiguracao.
    # Sempre passado explicitamente por _RuntimeConfigStore.set() (nunca
    # via default_factory=time.monotonic aqui): um default_factory captura
    # o objeto funcao de `time.monotonic` na definicao da classe, entao
    # `monkeypatch.setattr(runtime_config.time, "monotonic", ...)` nos
    # testes nao teria efeito nenhum sobre ele.
    activated_at: float = 0.0


# Referencia usada pela rampa de degradacao_progressiva quando ela e
# ativada so via variavel de ambiente no boot (sem nenhum override de
# runtime ainda) - equivalente a "rampa comecou quando o processo subiu".
_PROCESS_START = time.monotonic()

_DEFAULT_PARAMS = ChaosTypeParams()


class _RuntimeConfigStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._override: ChaosRuntimeOverride | None = None
        self._kafka_lag_message_count = 0

    def set(
        self,
        *,
        enabled: bool,
        failure_rate: float,
        failure_types: list[str],
        duration_seconds: float | None,
        params: ChaosTypeParams,
    ) -> ChaosRuntimeOverride:
        now = time.monotonic()
        expires_at = now + duration_seconds if duration_seconds is not None else None
        override = ChaosRuntimeOverride(
            enabled=enabled,
            failure_rate=failure_rate,
            failure_types=list(failure_types),
            expires_at=expires_at,
            params=params,
            activated_at=now,
        )
        with self._lock:
            self._override = override
            # Toda reconfiguracao e um experimento novo (decisao confirmada
            # com o usuario) - contador de kafka_lag reinicia junto.
            self._kafka_lag_message_count = 0
        return override

    def clear(self) -> None:
        with self._lock:
            self._override = None
            self._kafka_lag_message_count = 0

    def get(self) -> ChaosRuntimeOverride | None:
        with self._lock:
            override = self._override
            if override is not None and override.expires_at is not None and time.monotonic() >= override.expires_at:
                self._override = None
                return None
            return override

    def next_kafka_lag_delay_ms(self, increment_ms: float, ceiling_ms: float) -> float:
        with self._lock:
            self._kafka_lag_message_count += 1
            return min(self._kafka_lag_message_count * increment_ms, ceiling_ms)


_store = _RuntimeConfigStore()


def set_runtime_override(
    *,
    enabled: bool,
    failure_rate: float,
    failure_types: list[str],
    duration_seconds: float | None,
    params: ChaosTypeParams | None = None,
) -> ChaosRuntimeOverride:
    return _store.set(
        enabled=enabled,
        failure_rate=failure_rate,
        failure_types=failure_types,
        duration_seconds=duration_seconds,
        params=params if params is not None else ChaosTypeParams(),
    )


def clear_runtime_override() -> None:
    """Usado pelos testes para isolar o estado global entre casos - nao ha
    endpoint publico equivalente (nao pedido pela spec: a duracao/janela
    e o mecanismo de reversao automatica previsto)."""
    _store.clear()


def get_runtime_override() -> ChaosRuntimeOverride | None:
    return _store.get()


def get_active_type_params() -> ChaosTypeParams:
    """Parametros dos tipos da Fase 2b - do override ativo, ou os
    defaults quando so ha configuracao via variavel de ambiente (ou
    nenhuma configuracao ainda)."""
    override = get_runtime_override()
    return override.params if override is not None else _DEFAULT_PARAMS


def get_activation_time() -> float:
    """Referencia de `time.monotonic()` para a rampa de
    degradacao_progressiva: quando o override atual foi criado, ou o
    momento em que o processo subiu se nao ha override (ativacao so por
    variavel de ambiente)."""
    override = get_runtime_override()
    return override.activated_at if override is not None else _PROCESS_START


def record_kafka_lag_message(increment_ms: float, ceiling_ms: float) -> float:
    """Chamado uma vez por mensagem afetada por kafka_lag - incrementa o
    contador (resetado a cada POST /internal/chaos/config) e retorna o
    atraso em ms para esta mensagem, capado em `ceiling_ms`."""
    return _store.next_kafka_lag_delay_ms(increment_ms, ceiling_ms)
