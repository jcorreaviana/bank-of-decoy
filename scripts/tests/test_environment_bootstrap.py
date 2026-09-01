"""Testes da logica pura de scripts/environment_bootstrap.py (issue #81) -
sem Docker/Postgres/rede reais. `wait_for_healthy` e testado com checks e
relogio falsos; `migration_commands`/`run_migrations`/`docker_compose_up`
com um `runner` falso no lugar de `subprocess.run`. A parte que fala com o
mundo real (`_http_check`, `_tcp_check`, `_postgres_database_check`, e o
proprio `docker` de fato subindo containers) e validada manualmente contra
o ambiente real (ver specs/tech/cold-start.md, secao "Validacao")."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

import environment_bootstrap as env_boot
from environment_bootstrap import (
    DOMAIN_DATABASES,
    HTTP_HEALTH_CHECKS,
    MIGRATION_SERVICES,
    TCP_HEALTH_CHECKS,
    HealthCheck,
    MigrationCommand,
    migration_commands,
    run_migrations,
    wait_for_healthy,
)


# --------------------------------------------------------------------------
# wait_for_healthy
# --------------------------------------------------------------------------


class _FakeClock:
    """Relogio falso: cada chamada a `sleep()` avanca `now()` pelo valor
    dormido, sem esperar de verdade - deixa o teste do timeout instantaneo."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleep_calls = 0

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleep_calls += 1
        self.t += seconds


def test_todos_saudaveis_de_primeira_nao_dorme():
    clock = _FakeClock()
    checks = [HealthCheck("a", lambda: True), HealthCheck("b", lambda: True)]

    wait_for_healthy(checks, timeout_seconds=10.0, poll_interval_seconds=1.0, sleep=clock.sleep, now=clock.now)

    assert clock.sleep_calls == 0


def test_check_fica_pendente_ate_ficar_saudavel_depois_de_algumas_tentativas():
    clock = _FakeClock()
    attempts = {"n": 0}

    def eventualmente_saudavel() -> bool:
        attempts["n"] += 1
        return attempts["n"] >= 3

    checks = [HealthCheck("servico", eventualmente_saudavel)]

    wait_for_healthy(checks, timeout_seconds=10.0, poll_interval_seconds=1.0, sleep=clock.sleep, now=clock.now)

    assert attempts["n"] == 3
    assert clock.sleep_calls == 2


def test_check_que_levanta_excecao_conta_como_ainda_nao_saudavel_sem_derrubar_o_loop():
    clock = _FakeClock()
    attempts = {"n": 0}

    def falha_depois_ok() -> bool:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise ConnectionError("recusado")
        return True

    checks = [HealthCheck("servico", falha_depois_ok)]

    wait_for_healthy(checks, timeout_seconds=10.0, poll_interval_seconds=1.0, sleep=clock.sleep, now=clock.now)

    assert attempts["n"] == 2


def test_timeout_falha_rapido_e_claro_nomeando_o_pendente():
    clock = _FakeClock()
    checks = [HealthCheck("nunca-fica-saudavel", lambda: False), HealthCheck("ok", lambda: True)]

    with pytest.raises(SystemExit) as exc_info:
        wait_for_healthy(checks, timeout_seconds=5.0, poll_interval_seconds=1.0, sleep=clock.sleep, now=clock.now)

    mensagem = str(exc_info.value)
    assert "nunca-fica-saudavel" in mensagem
    assert "ok" not in mensagem.split(":")[-1]  # o que ja ficou saudavel nao aparece como pendente


def test_on_healthy_e_chamado_uma_vez_por_check_que_fica_saudavel():
    clock = _FakeClock()
    vistos = []
    checks = [HealthCheck("a", lambda: True), HealthCheck("b", lambda: True)]

    wait_for_healthy(
        checks, timeout_seconds=10.0, poll_interval_seconds=1.0, sleep=clock.sleep, now=clock.now, on_healthy=vistos.append
    )

    assert sorted(vistos) == ["a", "b"]


# --------------------------------------------------------------------------
# Cobertura dos componentes exigidos pela issue #81 ("todos os servicos:
# onboarding, account, pix-key, transaction, agent_ops, Postgres, Kafka,
# Prometheus, Grafana") - protege contra um check ser removido em silencio
# no futuro.
# --------------------------------------------------------------------------


def test_default_health_checks_cobre_os_5_bancos_de_dominio():
    assert set(DOMAIN_DATABASES) == {"onboarding", "account", "pix_key", "transaction", "agent_ops"}


def test_default_health_checks_cobre_os_4_servicos_http_de_dominio():
    for service in ["onboarding-service", "account-service", "pix-key-service", "transaction-service"]:
        assert service in HTTP_HEALTH_CHECKS


def test_default_health_checks_cobre_prometheus_grafana_e_kafka():
    assert "prometheus" in HTTP_HEALTH_CHECKS
    assert "grafana" in HTTP_HEALTH_CHECKS
    assert "kafka" in TCP_HEALTH_CHECKS


def test_build_default_health_checks_gera_um_check_por_componente():
    checks = env_boot.build_default_health_checks()
    names = {c.name for c in checks}

    expected = {f"postgres:{db}" for db in DOMAIN_DATABASES} | set(HTTP_HEALTH_CHECKS) | set(TCP_HEALTH_CHECKS)
    assert names == expected


# --------------------------------------------------------------------------
# migration_commands / run_migrations - achado da issue #75 generalizado:
# cada migration roda com cwd=pasta do proprio servico, nunca a raiz do repo.
# --------------------------------------------------------------------------


def test_migration_commands_usa_cwd_da_pasta_do_proprio_servico_nao_a_raiz_do_repo(tmp_path):
    commands = migration_commands(repo_root=tmp_path)

    assert len(commands) == len(MIGRATION_SERVICES)
    for cmd in commands:
        assert cmd.cwd == tmp_path / cmd.service_dir
        assert cmd.cwd != tmp_path
        assert cmd.database in cmd.database_url
        assert "localhost" in cmd.database_url


def test_migration_commands_cobre_os_5_servicos_esperados():
    commands = migration_commands()
    service_dirs = {cmd.service_dir for cmd in commands}

    assert service_dirs == {
        "onboarding-service",
        "account-service",
        "pix-key-service",
        "transaction-service",
        "agent-ops-service",
    }


class _FakeRunner:
    """Substitui subprocess.run - grava os argumentos de cada chamada
    (inclusive `cwd`) sem executar nada de verdade, e permite configurar
    qual servico deve falhar."""

    def __init__(self, fail_for: str | None = None) -> None:
        self.fail_for = fail_for
        self.calls: list[dict] = []

    def __call__(self, cmd, *, cwd=None, env=None):
        self.calls.append({"cmd": cmd, "cwd": cwd, "env": env})

        class _Result:
            pass

        result = _Result()
        cwd_name = Path(cwd).name if cwd else ""
        result.returncode = 1 if self.fail_for and self.fail_for in cwd_name else 0
        return result


def test_run_migrations_roda_alembic_com_cwd_correto_para_cada_servico():
    runner = _FakeRunner()
    commands = migration_commands()

    run_migrations(commands, runner=runner)

    assert len(runner.calls) == len(commands)
    for call, cmd in zip(runner.calls, commands):
        assert call["cwd"] == cmd.cwd
        assert call["cmd"][1:4] == ["-m", "alembic", "upgrade"]
        assert call["env"]["DATABASE_URL"] == cmd.database_url


def test_run_migrations_falha_rapido_e_identifica_o_servico_e_o_cwd_da_falha():
    commands = migration_commands()
    falha_em = commands[2].service_dir  # pix-key-service
    runner = _FakeRunner(fail_for=falha_em)

    with pytest.raises(SystemExit) as exc_info:
        run_migrations(commands, runner=runner)

    mensagem = str(exc_info.value)
    assert falha_em in mensagem
    assert str(commands[2].cwd) in mensagem
    # para no primeiro que falha - nao tenta os servicos seguintes
    assert len(runner.calls) == 3


def test_run_migrations_chama_on_start_e_on_done_por_comando_bem_sucedido():
    runner = _FakeRunner()
    commands = migration_commands()
    started = []
    done = []

    run_migrations(commands, runner=runner, on_start=lambda cmd: started.append(cmd.service_dir), on_done=lambda cmd: done.append(cmd.service_dir))

    assert started == [cmd.service_dir for cmd in commands]
    assert done == started


def test_migration_command_dataclass_e_um_pequeno_registro_direto():
    cmd = MigrationCommand(service_dir="x", database="y", cwd=Path("/tmp/x"), database_url="postgresql://y")
    assert cmd.service_dir == "x"


# --------------------------------------------------------------------------
# docker_compose_up
# --------------------------------------------------------------------------


class _FakeComposeRunner:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.calls: list[dict] = []

    def __call__(self, args, *, cwd=None):
        self.calls.append({"args": args, "cwd": cwd})

        class _Result:
            pass

        result = _Result()
        result.returncode = self.returncode
        return result


def test_docker_compose_up_inclui_build_quando_pedido():
    runner = _FakeComposeRunner()

    env_boot.docker_compose_up(Path("docker-compose.test.yml"), build=True, runner=runner)

    assert "--build" in runner.calls[0]["args"]


def test_docker_compose_up_nao_inclui_build_quando_nao_pedido():
    runner = _FakeComposeRunner()

    env_boot.docker_compose_up(Path("docker-compose.test.yml"), build=False, runner=runner)

    assert "--build" not in runner.calls[0]["args"]


def test_docker_compose_up_falha_rapido_se_docker_compose_falhar():
    runner = _FakeComposeRunner(returncode=1)

    with pytest.raises(SystemExit):
        env_boot.docker_compose_up(Path("docker-compose.test.yml"), build=True, runner=runner)
