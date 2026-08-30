import os
from unittest.mock import patch

import anyio
import pytest
from claude_agent_sdk import ResultMessage

from agent_local.sdk_invocation import (
    ALLOWED_TOOLS,
    _ALLOWED_ENV_PASSTHROUGH,
    _deny_out_of_scope_tools,
    _minimal_subprocess_env,
    build_task_prompt,
    invoke_sdk,
)


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


def test_minimal_subprocess_env_reduz_a_so_a_lista_permitida() -> None:
    """Achado real (vazamento de isolamento ao processar #55): variaveis
    que identificam a sessao IDE anexada (CLAUDE_CODE_MESSAGING_SOCKET e
    afins) sao herdadas por default pelo subprocess do SDK - o CLI
    empacotado usa esse canal pra se conectar ao IDE, fazendo Read/Edit
    resolverem contra a working tree real do operador em vez do `cwd`
    isolado. Lista POSITIVA, nao negativa - uma variavel de vazamento nova
    amanha continua bloqueada por definicao, sem precisar atualizar uma
    lista de bloqueio."""
    with patch.dict(
        os.environ,
        {
            "PATH": "/usr/bin",
            "CLAUDE_CODE_MESSAGING_SOCKET": "\\\\.\\pipe\\LOCAL\\cc-msg-fake",
            "CLAUDE_CODE_MESSAGING_TOKEN": "fake-token",
            "CLAUDE_CODE_SESSION_ID": "fake-session",
            "CLAUDE_PID": "12345",
            "VSCODE_PID": "999",
            "ALGUMA_VARIAVEL_FUTURA_DESCONHECIDA": "qualquer-coisa",
        },
        clear=False,
    ):
        with _minimal_subprocess_env():
            assert set(os.environ.keys()) <= set(_ALLOWED_ENV_PASSTHROUGH)
            assert os.environ.get("PATH") == "/usr/bin"
            assert "CLAUDE_CODE_MESSAGING_SOCKET" not in os.environ
            assert "CLAUDE_CODE_MESSAGING_TOKEN" not in os.environ
            assert "CLAUDE_CODE_SESSION_ID" not in os.environ
            assert "CLAUDE_PID" not in os.environ
            assert "VSCODE_PID" not in os.environ
            assert "ALGUMA_VARIAVEL_FUTURA_DESCONHECIDA" not in os.environ


def test_minimal_subprocess_env_restaura_tudo_depois_mesmo_com_excecao() -> None:
    with patch.dict(os.environ, {"CLAUDE_CODE_MESSAGING_SOCKET": "fake"}, clear=False):
        before = dict(os.environ)
        with pytest.raises(RuntimeError):
            with _minimal_subprocess_env():
                assert "CLAUDE_CODE_MESSAGING_SOCKET" not in os.environ
                raise RuntimeError("falha simulada dentro do bloco")

        assert dict(os.environ) == before


def test_invoke_sdk_reduz_environ_so_durante_a_chamada_ao_sdk() -> None:
    """Verifica de ponta a ponta (sem mockar _minimal_subprocess_env) que
    invoke_sdk realmente reduz o ambiente no momento em que o SDK roda, e
    restaura completamente depois - nao so que a funcao auxiliar funciona
    isolada."""
    captured_env_during_call: dict = {}

    async def _spy_query(*, prompt, options):
        captured_env_during_call.update(os.environ)
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="s1",
            total_cost_usd=0.0,
            result="ok",
        )

    with (
        patch.dict(os.environ, {"CLAUDE_CODE_MESSAGING_SOCKET": "fake-vazamento"}, clear=False),
        patch("agent_local.sdk_invocation.query", _spy_query),
    ):
        before = dict(os.environ)
        invoke_sdk("prompt", cwd=".", model="m", max_turns=1, timeout_seconds=5.0)
        after = dict(os.environ)

    assert "CLAUDE_CODE_MESSAGING_SOCKET" not in captured_env_during_call
    assert after == before  # restaurado por completo apos a chamada
