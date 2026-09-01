"""Bootstrap idempotente do ambiente efemero de validacao
(docker-compose.test.yml) - extraido de scripts/validation_window.py
(issue #54) para ser compartilhado com scripts/cold_start.py (issue #81),
evitando duplicar subida/health-check/migrations nos dois scripts e correr o
risco de eles divergirem com o tempo (mesmo racional de v11/v38 do
documento de escopo).

Health check REAL (nao um sleep fixo) para cada peca do ambiente:
- Postgres: nao basta o healthcheck nativo do container (so confirma que o
  servidor aceita conexao no banco default `bank` - nao que os 5 bancos de
  dominio foram de fato criados pelo init script). Conecta em cada um dos 5
  bancos via psycopg2 (`SELECT 1`), o que tambem cobre `agent_ops` (issue
  #81 pede health check dele explicitamente, apesar de nao ser um container
  HTTP proprio - so uma database dentro do Postgres).
- Kafka: connect TCP na porta do listener exposto ao host (nao ha
  dependencia nova de cliente Kafka so para isso).
- Prometheus/Grafana: endpoint HTTP de prontidao de cada um
  (`/-/ready`, `/api/health`).
- Os 4 servicos de dominio: `/health` (mesmo padrao ja usado por
  validation_window.py antes desta extracao).
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COMPOSE_FILE = REPO_ROOT / "docker-compose.test.yml"

# {diretorio do componente: nome do banco} - cada migration roda com
# cwd=REPO_ROOT/servico (nunca com -c/cwd na raiz do repo) e
# DATABASE_URL apontando para o banco daquele servico. Achado da issue #75
# generalizado aqui: nunca deixar caminho ambiguo entre o cwd do script e o
# cwd esperado por cada subcomando invocado.
MIGRATION_SERVICES: dict[str, str] = {
    "onboarding-service": "onboarding",
    "account-service": "account",
    "pix-key-service": "pix_key",
    "transaction-service": "transaction",
    "agent-ops-service": "agent_ops",
}

DOMAIN_DATABASES = ["onboarding", "account", "pix_key", "transaction", "agent_ops"]

HTTP_HEALTH_CHECKS: dict[str, str] = {
    "onboarding-service": "http://localhost:8001/health",
    "account-service": "http://localhost:8002/health",
    "pix-key-service": "http://localhost:8003/health",
    "transaction-service": "http://localhost:8004/health",
    "prometheus": "http://localhost:9090/-/ready",
    "grafana": "http://localhost:3000/api/health",
}

# host, porta - listener Kafka exposto ao host (KAFKA_ADVERTISED_LISTENERS,
# PLAINTEXT_HOST://localhost:29092 em docker-compose.test.yml).
TCP_HEALTH_CHECKS: dict[str, tuple[str, int]] = {
    "kafka": ("localhost", 29092),
}

POSTGRES_HOST = "localhost"
POSTGRES_PORT = 5432
POSTGRES_USER = "bank"
POSTGRES_PASSWORD = "bank"


def _venv_python(component_dir: Path) -> Path:
    windows_exe = component_dir / ".venv" / "Scripts" / "python.exe"
    if windows_exe.exists():
        return windows_exe
    return component_dir / ".venv" / "bin" / "python"


# --------------------------------------------------------------------------
# Health checks - cada `check()` e uma chamada de rede real e barata (timeout
# curto), nunca um sleep fixo. A funcao que decide "pendente ate quando" fica
# separada (`wait_for_healthy`) para ser testavel sem rede/Docker real.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HealthCheck:
    name: str
    check: Callable[[], bool]


def _http_check(url: str, timeout: float = 3.0) -> bool:
    import httpx

    try:
        resp = httpx.get(url, timeout=timeout)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def _tcp_check(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _postgres_database_check(database: str, timeout: float = 3.0) -> bool:
    import psycopg2

    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            dbname=database,
            connect_timeout=int(timeout),
        )
    except psycopg2.OperationalError:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except Exception:  # noqa: BLE001 - qualquer erro de query tambem conta como "nao saudavel ainda"
        return False
    finally:
        conn.close()


def build_default_health_checks() -> list[HealthCheck]:
    checks = [HealthCheck(f"postgres:{db}", lambda db=db: _postgres_database_check(db)) for db in DOMAIN_DATABASES]
    checks += [HealthCheck(name, lambda url=url: _http_check(url)) for name, url in HTTP_HEALTH_CHECKS.items()]
    checks += [
        HealthCheck(name, lambda host=host, port=port: _tcp_check(host, port))
        for name, (host, port) in TCP_HEALTH_CHECKS.items()
    ]
    return checks


def wait_for_healthy(
    checks: list[HealthCheck],
    *,
    timeout_seconds: float = 180.0,
    poll_interval_seconds: float = 3.0,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    on_healthy: Callable[[str], None] = lambda name: None,
) -> None:
    """Espera todo `check()` retornar True, tentando de novo a cada
    `poll_interval_seconds` ate `timeout_seconds`. `check()` que levanta
    excecao conta como "ainda nao saudavel" (servico pode estar recusando
    conexao/DNS ainda nao resolvendo logo apos o `up`), nunca derruba o
    loop. Falha rapido e claro ao final: `SystemExit` nomeando exatamente
    quais checks ficaram pendentes, nunca um timeout silencioso."""
    deadline = now() + timeout_seconds
    pending = {c.name: c for c in checks}
    while pending and now() < deadline:
        for name, c in list(pending.items()):
            try:
                healthy = c.check()
            except Exception:  # noqa: BLE001 - erro de rede/driver conta como "ainda nao saudavel"
                healthy = False
            if healthy:
                pending.pop(name)
                on_healthy(name)
        if pending:
            sleep(poll_interval_seconds)
    if pending:
        raise SystemExit(
            f"Ambiente nao ficou saudavel dentro de {timeout_seconds:.0f}s: {sorted(pending)}. "
            "Confira 'docker compose -f docker-compose.test.yml logs <servico>' para o servico pendente."
        )


# --------------------------------------------------------------------------
# docker compose up
# --------------------------------------------------------------------------


def docker_compose_up(
    compose_file: Path = DEFAULT_COMPOSE_FILE, *, build: bool = True, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run
) -> None:
    args = ["docker", "compose", "-f", str(compose_file), "up", "-d"]
    if build:
        args.append("--build")
    result = runner(args, cwd=REPO_ROOT)
    if result.returncode != 0:
        raise SystemExit(f"'docker compose -f {compose_file} up -d' falhou (returncode={result.returncode}).")


# --------------------------------------------------------------------------
# Migrations - cada uma roda de DENTRO da pasta do proprio servico
# (cwd=REPO_ROOT/service_dir), nunca com -c/cwd na raiz do repo (issue #75).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MigrationCommand:
    service_dir: str
    database: str
    cwd: Path
    database_url: str


def migration_commands(
    services: dict[str, str] = MIGRATION_SERVICES,
    *,
    host: str = POSTGRES_HOST,
    port: int = POSTGRES_PORT,
    repo_root: Path = REPO_ROOT,
) -> list[MigrationCommand]:
    return [
        MigrationCommand(
            service_dir=service_dir,
            database=database,
            cwd=repo_root / service_dir,
            database_url=f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{host}:{port}/{database}",
        )
        for service_dir, database in services.items()
    ]


def run_migrations(
    commands: list[MigrationCommand],
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    on_start: Callable[[MigrationCommand], None] = lambda cmd: None,
    on_done: Callable[[MigrationCommand], None] = lambda cmd: None,
) -> None:
    """Roda `alembic upgrade head` (idempotente) para cada comando, sempre
    com `cwd=comando.cwd` (a pasta do proprio servico) - nunca a raiz do
    repo. Falha rapido no primeiro servico que falhar, com mensagem
    nomeando exatamente qual servico/banco/cwd foi usado, para nunca deixar
    ambiguo qual subcomando falhou nem onde ele rodou."""
    for cmd in commands:
        on_start(cmd)
        python = _venv_python(cmd.cwd)
        env = {**os.environ, "DATABASE_URL": cmd.database_url}
        result = runner([str(python), "-m", "alembic", "upgrade", "head"], cwd=cmd.cwd, env=env)
        if result.returncode != 0:
            raise SystemExit(
                f"Migration falhou para '{cmd.service_dir}' (banco={cmd.database}, cwd={cmd.cwd}, "
                f"returncode={result.returncode})."
            )
        on_done(cmd)
