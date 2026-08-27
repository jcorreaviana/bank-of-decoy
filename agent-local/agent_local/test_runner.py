"""Roda a suite de testes do(s) servico(s) afetado(s) pelo diff, captura
cobertura (`pytest --cov`) e tamanho do diff (`git diff --stat`)
(specs/business/14-agente-local.md, passo 5).

TESTING=true e setado por este modulo ao invocar pytest, nunca deixado a
cargo de quem chama - a trava `shared/test_safety` (specs/tech/testing.md)
aborta qualquer fixture destrutiva sem essa variavel. `DATABASE_URL` deve
sempre apontar para um banco descartavel (nunca o persistente principal)."""

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SERVICE_DIRS = ["onboarding-service", "account-service", "pix-key-service", "transaction-service"]

_DIFF_STAT_SUMMARY = re.compile(r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?")
_COVERAGE_TOTAL = re.compile(r"TOTAL\s+\d+\s+\d+\s+(\d+)%")


@dataclass(frozen=True)
class DiffStat:
    files_changed: list[str]
    lines_changed: int


@dataclass(frozen=True)
class TestRunResult:
    service: str
    passed: bool
    coverage_fraction: float
    output: str


def get_diff_stat(cwd: str, base_ref: str = "main") -> DiffStat:
    files_result = subprocess.run(
        ["git", "diff", f"{base_ref}...HEAD", "--name-only"], capture_output=True, text=True, encoding="utf-8", cwd=cwd, check=True
    )
    files_changed = [line for line in files_result.stdout.splitlines() if line.strip()]

    stat_result = subprocess.run(
        ["git", "diff", f"{base_ref}...HEAD", "--stat"], capture_output=True, text=True, encoding="utf-8", cwd=cwd, check=True
    )
    summary_match = _DIFF_STAT_SUMMARY.search(stat_result.stdout)
    lines_changed = 0
    if summary_match:
        insertions = int(summary_match.group(2) or 0)
        deletions = int(summary_match.group(3) or 0)
        lines_changed = insertions + deletions

    return DiffStat(files_changed=files_changed, lines_changed=lines_changed)


def detect_affected_services(files_changed: list[str]) -> list[str]:
    affected = []
    for service_dir in SERVICE_DIRS:
        if any(f.startswith(f"{service_dir}/") for f in files_changed):
            affected.append(service_dir)
    return affected


def run_tests_for_service(service: str, repo_dir: str, test_database_url: str) -> TestRunResult:
    service_dir = Path(repo_dir) / service
    venv_python = service_dir / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        venv_python = service_dir / ".venv" / "bin" / "python"

    if not venv_python.exists():
        # `sys.executable` (nao "python" cru) - em Windows, "python" no PATH
        # pode resolver para o alias de app da Microsoft Store, que cria um
        # venv incompleto (sem python.exe copiado) sem erro visivel.
        subprocess.run([sys.executable, "-m", "venv", ".venv"], cwd=service_dir, check=True)
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "-q", "-r", "requirements.txt"], cwd=service_dir, check=True
        )

    env = {"TESTING": "true", "DATABASE_URL": test_database_url}
    import os

    full_env = {**os.environ, **env}

    result = subprocess.run(
        [str(venv_python), "-m", "pytest", "--cov=app", "--cov-report=term", "-q"],
        cwd=service_dir,
        env=full_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    coverage_match = _COVERAGE_TOTAL.search(result.stdout)
    coverage_fraction = int(coverage_match.group(1)) / 100.0 if coverage_match else 0.0

    return TestRunResult(
        service=service,
        passed=result.returncode == 0,
        coverage_fraction=coverage_fraction,
        output=result.stdout + result.stderr,
    )
