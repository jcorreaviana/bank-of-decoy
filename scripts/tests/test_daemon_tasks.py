"""Testes da logica pura de scripts/daemon_tasks.py (issue #81) - sem
PowerShell/Task Scheduler reais, sempre com um `runner` falso no lugar de
`subprocess.run`. A validacao contra o Task Scheduler de verdade (task
registrada, disparada, daemon rodando sem ancestralidade de sessao IDE) e
manual (ver specs/tech/cold-start.md, secao "Validacao")."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import daemon_tasks
from daemon_tasks import DAEMON_TASKS, DaemonTask, register_command, start, start_command, task_exists


class _FakeResult:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeRunner:
    def __init__(self, *, query_returncode: int = 0, register_returncode: int = 0, run_returncode: int = 0) -> None:
        self.query_returncode = query_returncode
        self.register_returncode = register_returncode
        self.run_returncode = run_returncode
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == "schtasks" and "/query" in args:
            return _FakeResult(self.query_returncode)
        if args[0] == "powershell":
            return _FakeResult(self.register_returncode)
        if args[0] == "schtasks" and "/run" in args:
            return _FakeResult(self.run_returncode, stderr="falha simulada" if self.run_returncode else "")
        raise AssertionError(f"chamada inesperada: {args}")


# --------------------------------------------------------------------------
# DAEMON_TASKS - cobertura dos dois daemons exigidos pela issue #81
# --------------------------------------------------------------------------


def test_daemon_tasks_cobre_agent_local_e_agent_preditivo():
    modules = {task.module for task in DAEMON_TASKS}
    assert modules == {"agent_local.polling", "agent_preditivo.polling"}


def test_daemon_tasks_tem_nomes_unicos():
    names = [task.task_name for task in DAEMON_TASKS]
    assert len(names) == len(set(names))


# --------------------------------------------------------------------------
# register_command / start_command - comandos puros, sem I/O
# --------------------------------------------------------------------------


def test_register_command_usa_working_directory_do_proprio_daemon_nao_a_raiz_do_repo():
    task = DaemonTask("Task-Teste", Path("/repo/agent-local"), "agent_local.polling")

    cmd = register_command(task)

    assert "-WorkingDirectory" in cmd
    wd_index = cmd.index("-WorkingDirectory") + 1
    assert cmd[wd_index] == str(task.component_dir)
    assert cmd[wd_index] != "/repo"


def test_register_command_passa_o_nome_da_task_e_o_modulo_correto():
    task = DaemonTask("Task-Teste", Path("/repo/agent-preditivo"), "agent_preditivo.polling")

    cmd = register_command(task)

    assert "-TaskName" in cmd
    assert cmd[cmd.index("-TaskName") + 1] == "Task-Teste"
    assert "-Arguments" in cmd
    assert cmd[cmd.index("-Arguments") + 1] == "-m agent_preditivo.polling"


def test_start_command_e_schtasks_run_com_o_nome_da_task():
    assert start_command("Task-Teste") == ["schtasks", "/run", "/tn", "Task-Teste"]


# --------------------------------------------------------------------------
# task_exists / start - orquestracao (registra so se preciso, dispara,
# falha rapido e claro se schtasks falhar)
# --------------------------------------------------------------------------


def test_task_exists_true_quando_query_retorna_0():
    runner = _FakeRunner(query_returncode=0)
    assert task_exists("Task-Teste", runner=runner) is True


def test_task_exists_false_quando_query_retorna_erro():
    runner = _FakeRunner(query_returncode=1)
    assert task_exists("Task-Teste", runner=runner) is False


def test_start_registra_so_quando_a_task_ainda_nao_existe():
    runner = _FakeRunner(query_returncode=1)  # task nao existe ainda
    task = DaemonTask("Task-Teste", Path("/repo/agent-local"), "agent_local.polling")
    registering_calls = []

    start(task, runner=runner, on_registering=registering_calls.append)

    assert registering_calls == [task]
    powershell_calls = [c for c in runner.calls if c[0] == "powershell"]
    assert len(powershell_calls) == 1


def test_start_nao_registra_de_novo_quando_a_task_ja_existe():
    runner = _FakeRunner(query_returncode=0)  # task ja existe
    task = DaemonTask("Task-Teste", Path("/repo/agent-local"), "agent_local.polling")
    registering_calls = []

    start(task, runner=runner, on_registering=registering_calls.append)

    assert registering_calls == []
    powershell_calls = [c for c in runner.calls if c[0] == "powershell"]
    assert len(powershell_calls) == 0


def test_start_dispara_schtasks_run_depois_de_garantir_o_registro():
    runner = _FakeRunner(query_returncode=0)
    task = DaemonTask("Task-Teste", Path("/repo/agent-local"), "agent_local.polling")
    started_calls = []

    start(task, runner=runner, on_started=started_calls.append)

    assert started_calls == [task]
    run_calls = [c for c in runner.calls if c[0] == "schtasks" and "/run" in c]
    assert run_calls == [["schtasks", "/run", "/tn", "Task-Teste"]]


def test_start_falha_rapido_e_claro_se_registro_falhar():
    runner = _FakeRunner(query_returncode=1, register_returncode=1)
    task = DaemonTask("Task-Teste", Path("/repo/agent-local"), "agent_local.polling")

    with pytest.raises(SystemExit) as exc_info:
        start(task, runner=runner)

    assert "Task-Teste" in str(exc_info.value)


def test_start_falha_rapido_e_claro_se_schtasks_run_falhar():
    runner = _FakeRunner(query_returncode=0, run_returncode=1)
    task = DaemonTask("Task-Teste", Path("/repo/agent-local"), "agent_local.polling")

    with pytest.raises(SystemExit) as exc_info:
        start(task, runner=runner)

    mensagem = str(exc_info.value)
    assert "Task-Teste" in mensagem
    assert "falha simulada" in mensagem


def test_start_all_inicia_os_dois_daemons_na_ordem():
    runner = _FakeRunner(query_returncode=0)
    started_calls = []

    daemon_tasks.start_all(runner=runner, on_started=started_calls.append)

    assert [task.task_name for task in started_calls] == [task.task_name for task in DAEMON_TASKS]
