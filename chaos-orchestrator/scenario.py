"""Parsing do cenario de cascata coordenada do chaos-orchestrator (issue #53,
specs/business/24-camada-caos-avancada.md) - um arquivo YAML descrevendo uma
timeline de ativacoes do endpoint POST /internal/chaos/config (issue #51,
shared/chaos/chaos/router.py) em multiplos servicos, coordenadas ao longo do
tempo desde o inicio da execucao do orquestrador.

Nomes de campo em ingles, espelhando 1:1 o ChaosConfigRequest da API dentro
de `params` (failure_rate, ramp_ceiling_seconds, lag_increment_ms, etc.) -
decisao confirmada com o usuario, para nao introduzir um segundo vocabulario
de parametros so para este arquivo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Mesmas portas de docker-compose.yml (publicadas direto pro host) - usadas
# como default para quem roda o orquestrador fora do Docker (o caso comum,
# ja que o script so faz chamadas HTTP, sem precisar estar na rede do
# compose). Sobrescrevivel por servico via `service_urls` no proprio YAML.
DEFAULT_SERVICE_URLS = {
    "onboarding-service": "http://localhost:8001",
    "account-service": "http://localhost:8002",
    "pix-key-service": "http://localhost:8003",
    "transaction-service": "http://localhost:8004",
}

# Espelha os campos de ChaosConfigRequest (shared/chaos/chaos/router.py) que
# fazem sentido dentro de `params` - `enabled`/`failure_types`/
# `duration_seconds` sao controlados pelo proprio orquestrador (payload.py),
# nunca pelo autor do cenario.
ALLOWED_PARAM_KEYS = {
    "failure_rate",
    "ramp_ceiling_seconds",
    "ramp_window_seconds",
    "lag_increment_ms",
    "lag_ceiling_ms",
    "kafka_delay_seconds",
}


class ScenarioError(ValueError):
    """Cenario YAML invalido - mensagem ja inclui contexto (indice do passo,
    servico, campo) suficiente para corrigir o arquivo sem ler este modulo."""


@dataclass(frozen=True)
class TimelineStep:
    service: str
    failure_types: list[str]
    start_minute: float
    duration_minutes: float
    params: dict = field(default_factory=dict)

    @property
    def end_minute(self) -> float:
        return self.start_minute + self.duration_minutes


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    steps: list[TimelineStep]
    service_urls: dict[str, str]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioError(message)


def _parse_params(raw: object, context: str) -> dict:
    if raw is None:
        return {}
    _require(isinstance(raw, dict), f"{context}: 'params' precisa ser um mapeamento")
    unknown = sorted(set(raw) - ALLOWED_PARAM_KEYS)
    _require(
        not unknown,
        f"{context}: chave(s) desconhecida(s) em 'params': {', '.join(unknown)} "
        f"(permitidas: {', '.join(sorted(ALLOWED_PARAM_KEYS))})",
    )
    for key, value in raw.items():
        _require(
            isinstance(value, (int, float)) and not isinstance(value, bool),
            f"{context}: 'params.{key}' precisa ser numero",
        )
    return dict(raw)


def _parse_step(raw: object, index: int) -> TimelineStep:
    _require(isinstance(raw, dict), f"timeline[{index}]: cada passo precisa ser um mapeamento")

    service = raw.get("service")
    _require(isinstance(service, str) and service, f"timeline[{index}]: campo 'service' obrigatorio")
    context = f"timeline[{index}] ({service})"

    failure_types = raw.get("failure_types")
    _require(
        isinstance(failure_types, list) and failure_types and all(isinstance(t, str) and t for t in failure_types),
        f"{context}: 'failure_types' precisa ser uma lista nao vazia de strings",
    )

    start_minute = raw.get("start_minute")
    _require(
        isinstance(start_minute, (int, float)) and not isinstance(start_minute, bool) and start_minute >= 0,
        f"{context}: 'start_minute' precisa ser numero >= 0",
    )

    duration_minutes = raw.get("duration_minutes")
    _require(
        isinstance(duration_minutes, (int, float)) and not isinstance(duration_minutes, bool) and duration_minutes > 0,
        f"{context}: 'duration_minutes' precisa ser numero > 0",
    )

    params = _parse_params(raw.get("params"), context)

    return TimelineStep(
        service=service,
        failure_types=list(failure_types),
        start_minute=float(start_minute),
        duration_minutes=float(duration_minutes),
        params=params,
    )


def load_scenario(path: str | Path) -> Scenario:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    _require(isinstance(raw, dict), "cenario YAML precisa ter um mapeamento na raiz")

    name = raw.get("name") or path.stem
    description = raw.get("description") or ""

    timeline_raw = raw.get("timeline")
    _require(isinstance(timeline_raw, list) and timeline_raw, "cenario precisa de pelo menos um passo em 'timeline'")

    steps = [_parse_step(step, i) for i, step in enumerate(timeline_raw)]

    service_urls = dict(DEFAULT_SERVICE_URLS)
    overrides = raw.get("service_urls") or {}
    _require(isinstance(overrides, dict), "'service_urls', se presente, precisa ser um mapeamento")
    service_urls.update(overrides)

    unknown_services = sorted({step.service for step in steps} - set(service_urls))
    _require(
        not unknown_services,
        "servico(s) sem URL conhecida - defina em 'service_urls': " + ", ".join(unknown_services),
    )

    return Scenario(name=name, description=description, steps=steps, service_urls=service_urls)
