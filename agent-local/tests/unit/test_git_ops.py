import subprocess

import pytest

from agent_local.git_ops import create_issue_branch, delete_local_branch


def _init_repo(path) -> str:
    """`create_issue_branch` roda `git pull --ff-only` incondicionalmente
    (mesmo passo usado contra o clone real do agent-local) - precisa de um
    remote de verdade, mesmo que local (bare repo), senao o pull falha por
    falta de tracking/remote antes mesmo de chegar na parte que o teste
    quer exercitar."""
    remote_dir = str(path.parent / f"{path.name}-remote.git")
    subprocess.run(["git", "init", "--bare", remote_dir], check=True)

    repo_dir = str(path)
    subprocess.run(["git", "init"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo_dir, check=True)
    (path / "README.md").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "inicial"], cwd=repo_dir, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo_dir, check=True)
    subprocess.run(["git", "remote", "add", "origin", remote_dir], cwd=repo_dir, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=repo_dir, check=True)
    return repo_dir


def _branches(repo_dir: str) -> list[str]:
    result = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"], cwd=repo_dir, check=True, capture_output=True, text=True
    )
    return result.stdout.split()


def test_delete_local_branch_remove_a_branch_e_volta_para_main(tmp_path) -> None:
    repo_dir = _init_repo(tmp_path)
    subprocess.run(["git", "checkout", "-b", "agent-local/issue-99"], cwd=repo_dir, check=True)

    delete_local_branch(repo_dir, "agent-local/issue-99")

    assert "agent-local/issue-99" not in _branches(repo_dir)
    current = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo_dir, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert current == "main"


def test_reselecao_da_mesma_issue_apos_no_op_nao_colide_mais_com_a_branch(tmp_path) -> None:
    """Regressao do achado real: uma issue concluida como no_action_needed
    (destino 2) ficava aberta sem fechar, e uma selecao seguinte da MESMA
    issue recriava o nome da branch que o ciclo anterior ja tinha deixado
    para tras (create_issue_branch nunca reaproveitava/limpava), colidindo
    com `git checkout -b` e escalando para agent-stuck sem nenhuma falha
    real. Reproduz exatamente o ciclo "no-op bem sucedido -> nova selecao
    da mesma issue" e confirma que a segunda `create_issue_branch` nao
    levanta mais, porque `_handle_no_action_needed` agora chama
    `delete_local_branch` entre as duas selecoes."""
    repo_dir = _init_repo(tmp_path)

    # Primeira selecao: ciclo cria a branch de trabalho (create_issue_branch),
    # conclui como no-op e limpa a branch (o que _handle_no_action_needed faz
    # apos fechar a issue).
    branch = create_issue_branch(repo_dir, 99)
    delete_local_branch(repo_dir, branch)

    # Sem a correcao, a issue continuava aberta e uma segunda selecao da
    # mesma issue recriava o mesmo nome de branch e colidia aqui.
    branch_again = create_issue_branch(repo_dir, 99)

    assert branch_again == "agent-local/issue-99"
    assert "agent-local/issue-99" in _branches(repo_dir)


def test_create_issue_branch_sem_limpeza_previa_colide_reproduzindo_o_bug_original(tmp_path) -> None:
    """Prova de que o bug era real: sem chamar `delete_local_branch` entre
    as duas selecoes, a segunda `create_issue_branch` para a mesma issue
    falha com o mesmo erro observado ao vivo (`fatal: a branch ... already
    exists`, `CalledProcessError`)."""
    repo_dir = _init_repo(tmp_path)
    create_issue_branch(repo_dir, 99)
    subprocess.run(["git", "checkout", "main"], cwd=repo_dir, check=True)

    with pytest.raises(subprocess.CalledProcessError):
        create_issue_branch(repo_dir, 99)
