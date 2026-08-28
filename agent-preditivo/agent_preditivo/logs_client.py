"""Cliente de logs estruturados dos 4 servicos.

Decisao de mecanismo (specs/business/13-agente-preditivo-registro.md pede
"o mecanismo mais simples possivel dado que hoje os logs vao para stdout
dos containers"): usa `docker logs <container> --since <janela>`
programaticamente via subprocess, em vez de montar uma stack de
agregacao (Loki/ELK) so para o agente. Cada linha ja e JSON estruturado
de uma linha so (specs/tech/logging.md), entao basta `subprocess.run` +
`json.loads` por linha - sem infraestrutura nova, sem tocar nos 4
servicos. Troca consciente: nao escala para producao multi-host (docker
logs so ve containers locais), mas essa e exatamente a mesma limitacao
do ambiente inteiro (tudo local, Fase 1-4).
"""

import json
import subprocess
from dataclasses import dataclass

CONTAINER_PREFIX = "bank-of-decoy-"


@dataclass(frozen=True)
class LogEntry:
    timestamp: str
    service_name: str
    level: str
    trace_id: str
    message: str
    context: dict
    raw: str


def _container_name(service: str) -> str:
    return f"{CONTAINER_PREFIX}{service}"


def fetch_logs(service: str, since: str = "5m") -> list[LogEntry]:
    """`since` aceita o mesmo formato de `docker logs --since` (ex. "5m", "1h")."""
    container = _container_name(service)
    try:
        result = subprocess.run(
            ["docker", "logs", "--since", since, container],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        return []

    entries: list[LogEntry] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        entries.append(
            LogEntry(
                timestamp=payload.get("timestamp", ""),
                service_name=payload.get("service_name", service),
                level=payload.get("level", ""),
                trace_id=payload.get("trace_id", ""),
                message=payload.get("message", ""),
                context=payload.get("context", {}),
                raw=line,
            )
        )
    return entries


def count_repeated_critical_or_error(entries: list[LogEntry]) -> dict[str, int]:
    """Conta ocorrencias de mensagem por (level, message), restrito a
    CRITICAL/ERROR - usado para o threshold de "log CRITICAL/ERROR repetido
    3+ vezes com a mesma mensagem em 5 min" (evita issue duplicada por
    linha de erro isolada).

    Entradas com `context.chaos_injected: true` (falha simulada pela
    camada de caos, specs/business/11-camada-caos.md) sao ignoradas aqui -
    esse threshold especifico e sobre erro real repetido; o sinal de
    taxa de erro/latencia continua disparando com o caos ligado, e e la
    que o design pretendido (docs/escopo-arquitetura.md v17) quer o efeito
    visivel (specs/business/21-filtro-caos-pipeline-agentes.md)."""
    counts: dict[str, int] = {}
    for entry in entries:
        if entry.level not in ("CRITICAL", "ERROR"):
            continue
        if entry.context.get("chaos_injected"):
            continue
        key = f"{entry.level}:{entry.message}"
        counts[key] = counts.get(key, 0) + 1
    return counts
