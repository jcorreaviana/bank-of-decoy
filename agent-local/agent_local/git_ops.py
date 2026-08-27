"""Clona/atualiza o repositorio e cria a branch de trabalho
(specs/business/14-agente-local.md, passo 4). Branch nomeada de forma
rastreavel: `agent-local/issue-<numero>`."""

import subprocess
from pathlib import Path


def branch_name(issue_number: int) -> str:
    return f"agent-local/issue-{issue_number}"


def ensure_repo_cloned(repo_url: str, clone_dir: str) -> str:
    path = Path(clone_dir)
    if not (path / ".git").exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", repo_url, str(path)], check=True)
    else:
        subprocess.run(["git", "checkout", "main"], cwd=path, check=True)
        subprocess.run(["git", "pull", "--ff-only"], cwd=path, check=True)
    return str(path)


def create_issue_branch(repo_dir: str, issue_number: int) -> str:
    name = branch_name(issue_number)
    subprocess.run(["git", "checkout", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "pull", "--ff-only"], cwd=repo_dir, check=True)
    subprocess.run(["git", "checkout", "-b", name], cwd=repo_dir, check=True)
    return name


def push_branch(repo_dir: str, branch: str) -> None:
    """Unico ponto do wrapper que faz `git push` - deliberadamente FORA do
    `allowed_tools` da invocacao do SDK (ver sdk_invocation.py): o modelo
    nunca decide subir codigo, so o codigo deterministico deste modulo,
    depois que o SDK ja terminou de rodar."""
    subprocess.run(["git", "push", "-u", "origin", branch], cwd=repo_dir, check=True)
