from unittest.mock import patch

import anyio
import pytest

from agent_local.sdk_invocation import ALLOWED_TOOLS, _deny_out_of_scope_tools, build_task_prompt, invoke_sdk


def test_allowed_tools_nunca_inclui_push_ou_pr() -> None:
    """Documenta a intencao de escopo (nao e a trava em si - ver
    _deny_out_of_scope_tools, que e o mecanismo verificado por teste real
    contra o SDK)."""
    joined = " ".join(ALLOWED_TOOLS).lower()
    assert "push" not in joined
    assert "gh pr" not in joined
    assert "gh issue" not in joined


def test_allowed_tools_escopo_exato_da_issue() -> None:
    assert ALLOWED_TOOLS == [
        "Read",
        "Edit",
        "Bash(pytest *)",
        "Bash(alembic *)",
        "Bash(git add *)",
        "Bash(git commit *)",
        "Bash(git diff *)",
        "Bash(git status *)",
    ]


def test_build_task_prompt_inclui_numero_titulo_e_corpo_da_issue() -> None:
    prompt = build_task_prompt(42, "Titulo da issue", "Corpo da issue", spec_text=None)
    assert "#42" in prompt
    assert "Titulo da issue" in prompt
    assert "Corpo da issue" in prompt


def test_build_task_prompt_instrui_nao_fazer_push_nem_pr() -> None:
    prompt = build_task_prompt(1, "x", "y", spec_text=None)
    assert "git push" in prompt


def test_build_task_prompt_inclui_spec_quando_fornecida() -> None:
    prompt = build_task_prompt(1, "x", "y", spec_text="conteudo da spec de referencia")
    assert "conteudo da spec de referencia" in prompt


def _call_deny(tool_name: str, input_data: dict):
    return anyio.run(_deny_out_of_scope_tools, tool_name, input_data, None)


def test_deny_bloqueia_git_push() -> None:
    result = _call_deny("Bash", {"command": "git push origin main"})
    assert type(result).__name__ == "PermissionResultDeny"


def test_deny_bloqueia_gh_pr() -> None:
    result = _call_deny("Bash", {"command": "gh pr create --title x"})
    assert type(result).__name__ == "PermissionResultDeny"


def test_deny_bloqueia_gh_issue() -> None:
    result = _call_deny("Bash", {"command": "gh issue close 1"})
    assert type(result).__name__ == "PermissionResultDeny"


def test_deny_bloqueia_bash_fora_dos_padroes_permitidos() -> None:
    result = _call_deny("Bash", {"command": "rm -rf /"})
    assert type(result).__name__ == "PermissionResultDeny"


def test_deny_permite_bash_com_padrao_permitido() -> None:
    for command in ["pytest --cov", "alembic upgrade head", "git add .", "git commit -m x", "git diff --stat", "git status"]:
        result = _call_deny("Bash", {"command": command})
        assert type(result).__name__ == "PermissionResultAllow", f"deveria permitir: {command}"


def test_deny_permite_read_e_edit() -> None:
    assert type(_call_deny("Read", {"file_path": "x.py"})).__name__ == "PermissionResultAllow"
    assert type(_call_deny("Edit", {"file_path": "x.py"})).__name__ == "PermissionResultAllow"


def test_deny_bloqueia_ferramentas_nao_read_edit_bash() -> None:
    for tool_name in ["Write", "Glob", "Grep", "WebFetch", "WebSearch"]:
        result = _call_deny(tool_name, {})
        assert type(result).__name__ == "PermissionResultDeny", f"deveria bloquear: {tool_name}"


def test_invoke_sdk_timeout_explicito_levanta_timeout_mesmo_sem_excecao_do_sdk() -> None:
    """specs/tech/error-handling.md: toda chamada ao SDK dentro de
    process_issue precisa de timeout explicito, para garantir que o
    tratamento pos-falha seja alcancado mesmo se o SDK travar sem lancar
    excecao nenhuma - simulado aqui com um `query` que nunca produz uma
    ResultMessage dentro da janela de timeout."""

    async def _hanging_query(*, prompt, options):
        await anyio.sleep(10)
        yield  # pragma: no cover - nunca alcancado, timeout dispara antes

    with patch("agent_local.sdk_invocation.query", _hanging_query):
        with pytest.raises(TimeoutError):
            invoke_sdk("prompt", cwd=".", model="m", max_turns=1, timeout_seconds=0.05)
