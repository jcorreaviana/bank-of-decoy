"""Lancamento dos daemons dos agentes (agent-local, agent-preditivo) via
Scheduled Task do Windows - issue #81, decisao registrada em
specs/tech/cold-start.md.

Ate aqui, o README (secao "Lancando os daemons") so recomendava por escrito
nao lancar `agent-local` como subtarefa em background de uma sessao
Claude Code/VS Code (achado real, issue #66/#86 - vazamento de isolamento
entre o subprocess do SDK e a working tree real do operador, via variavel
de ambiente e via arquivo de lock de sessao IDE respectivamente). Isso
dependia inteiramente da disciplina do operador lembrar da recomendacao a
cada cold start.

Este modulo torna o isolamento estrutural: cada daemon nasce como processo
filho do servico Task Scheduler do Windows (svchost), nao da sessao que
disparou `schtasks /run` - mesmo que essa sessao seja um terminal integrado
do Claude Code/VS Code. O ambiente do processo filho vem do registro
(HKCU\\Environment), nunca da arvore de processos de quem chamou `/run`.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTER_SCRIPT = REPO_ROOT / "scripts" / "register_daemon_task.ps1"


def _venv_python(component_dir: Path) -> Path:
    windows_exe = component_dir / ".venv" / "Scripts" / "python.exe"
    if windows_exe.exists():
        return windows_exe
    return component_dir / ".venv" / "bin" / "python"


@dataclass(frozen=True)
class DaemonTask:
    task_name: str
    component_dir: Path
    module: str


DAEMON_TASKS: list[DaemonTask] = [
    DaemonTask("BankOfDecoy-AgentLocal", REPO_ROOT / "agent-local", "agent_local.polling"),
    DaemonTask("BankOfDecoy-AgentPreditivo", REPO_ROOT / "agent-preditivo", "agent_preditivo.polling"),
]


def task_exists(task_name: str, *, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> bool:
    result = runner(["schtasks", "/query", "/tn", task_name], capture_output=True, text=True)
    return result.returncode == 0


def register_command(task: DaemonTask) -> list[str]:
    """Comando puro (sem I/O) - testavel sem PowerShell/Task Scheduler
    reais. `-WorkingDirectory` aponta para `task.component_dir` (a pasta do
    proprio daemon), nunca `REPO_ROOT` - mesmo principio da issue #75
    aplicado aqui: o cwd do processo lancado precisa ser inequivoco."""
    python = _venv_python(task.component_dir)
    return [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(REGISTER_SCRIPT),
        "-TaskName",
        task.task_name,
        "-Python",
        str(python),
        "-Arguments",
        f"-m {task.module}",
        "-WorkingDirectory",
        str(task.component_dir),
    ]


def register(task: DaemonTask, *, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
    result = runner(register_command(task))
    if result.returncode != 0:
        raise SystemExit(f"Falha ao registrar a Scheduled Task '{task.task_name}' (returncode={result.returncode}).")


def start_command(task_name: str) -> list[str]:
    return ["schtasks", "/run", "/tn", task_name]


def start(
    task: DaemonTask,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    on_registering: Callable[[DaemonTask], None] = lambda task: None,
    on_started: Callable[[DaemonTask], None] = lambda task: None,
) -> None:
    """Registra a task sob demanda (so na primeira vez - idempotente, task
    ja registrada nunca e recriada em cold starts seguintes) e dispara
    `schtasks /run`. Falha rapido e claro se o registro ou o disparo
    falhar."""
    if not task_exists(task.task_name, runner=runner):
        on_registering(task)
        register(task, runner=runner)
    result = runner(start_command(task.task_name), capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"Falha ao iniciar a Scheduled Task '{task.task_name}' via 'schtasks /run' "
            f"(returncode={result.returncode}): {result.stderr or result.stdout}"
        )
    on_started(task)


def start_all(
    tasks: list[DaemonTask] = DAEMON_TASKS,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    on_registering: Callable[[DaemonTask], None] = lambda task: None,
    on_started: Callable[[DaemonTask], None] = lambda task: None,
) -> None:
    for task in tasks:
        start(task, runner=runner, on_registering=on_registering, on_started=on_started)
