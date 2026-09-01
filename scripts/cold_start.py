"""Cold start automatizado do ambiente de validacao (issue #81).

Substitui a operacao manual multi-terminal documentada ate aqui: antes, o
operador precisava (1) subir `docker-compose.test.yml` e acompanhar os logs
manualmente pra saber quando cada servico tinha ficado pronto, (2) abrir um
terminal por servico (5 no total) pra rodar `alembic upgrade head` na pasta
certa de cada um, e (3) abrir mais dois terminais - um por daemon
(agent-local, agent-preditivo) - tomando cuidado pra nenhum deles ser
subtarefa de uma sessao Claude Code/VS Code (issue #66/#86). Este script
substitui os passos (1)-(2) por uma chamada unica, idempotente e failfast
(scripts/environment_bootstrap.py, compartilhado com
scripts/validation_window.py) e o passo (3) por Scheduled Tasks do Windows
(scripts/daemon_tasks.py) - ver specs/tech/cold-start.md para o design
completo e o racional de cada decisao.

Uso:
    scripts/.venv/Scripts/python.exe scripts/cold_start.py
    scripts/.venv/Scripts/python.exe scripts/cold_start.py --no-build          # reaproveita imagens ja construidas
    scripts/.venv/Scripts/python.exe scripts/cold_start.py --skip-daemons      # so infra (compose+health+migrations)
    scripts/.venv/Scripts/python.exe scripts/cold_start.py --skip-up --skip-migrations --skip-daemons  # so os daemons
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import daemon_tasks
import environment_bootstrap as env_boot


def log(event: str, **fields) -> None:
    parts = " ".join(f"{k}={v}" for k, v in fields.items())
    print(f"[cold-start] {event}" + (f" ({parts})" if parts else ""), flush=True)


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--compose-file", type=Path, default=env_boot.DEFAULT_COMPOSE_FILE)
    parser.add_argument("--no-build", action="store_true", help="pula '--build' (assume imagens ja construidas)")
    parser.add_argument("--skip-up", action="store_true", help="assume que o ambiente ja esta no ar")
    parser.add_argument("--skip-migrations", action="store_true", help="pula 'alembic upgrade head' nos 5 servicos")
    parser.add_argument("--skip-daemons", action="store_true", help="nao inicia agent-local/agent-preditivo")
    parser.add_argument("--health-timeout-seconds", type=float, default=180.0)
    args = parser.parse_args(argv)

    if not args.skip_up:
        log("subindo_ambiente", compose_file=str(args.compose_file), build=not args.no_build)
        env_boot.docker_compose_up(args.compose_file, build=not args.no_build)

        log("aguardando_ambiente_saudavel", timeout_seconds=args.health_timeout_seconds)
        env_boot.wait_for_healthy(
            env_boot.build_default_health_checks(),
            timeout_seconds=args.health_timeout_seconds,
            on_healthy=lambda name: log("saudavel", componente=name),
        )
    else:
        log("pulando_subida_do_ambiente")

    if not args.skip_migrations:
        log("aplicando_migrations")
        env_boot.run_migrations(
            env_boot.migration_commands(),
            on_start=lambda cmd: log("aplicando_migration", servico=cmd.service_dir, banco=cmd.database),
            on_done=lambda cmd: log("migration_aplicada", servico=cmd.service_dir),
        )
    else:
        log("pulando_migrations")

    if not args.skip_daemons:
        log("iniciando_daemons_via_scheduled_task")
        daemon_tasks.start_all(
            on_registering=lambda task: log("registrando_scheduled_task", task=task.task_name),
            on_started=lambda task: log("daemon_iniciado", task=task.task_name),
        )
    else:
        log("pulando_daemons")

    log(
        "cold_start_concluido",
        mensagem=(
            "ambiente no ar, migrations aplicadas"
            + ("" if args.skip_daemons else ", daemons rodando via Scheduled Task")
            + ". Nenhum passo manual do operador foi necessario."
        ),
    )


if __name__ == "__main__":
    sys.exit(main())
