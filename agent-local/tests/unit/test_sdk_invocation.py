import os
from pathlib import Path
from unittest.mock import patch

import anyio
import pytest
from claude_agent_sdk import ResultMessage

from agent_local.sdk_invocation import (
    ALLOWED_TOOLS,
    _ALLOWED_ENV_PASSTHROUGH,
    _make_deny_out_of_scope_tools,
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
    """Issue #76: "Bash" e "PowerShell" sao ferramentas distintas no CLI
    empacotado (confirmado contra o SDK real, ver docstring de
    `sdk_invocation.py`) - cada padrao de git/teste precisa de uma entrada
    espelhada para cada uma, senao o modelo cai em negacao pelo motor de
    regras nativo do CLI ao escolher a ferramenta que nao tem entrada."""
    assert ALLOWED_TOOLS == [
        "Read",
        "Edit(**)",
        "Bash(pytest *)",
        "Bash(alembic *)",
        "Bash(git add *)",
        "Bash(git commit *)",
        "Bash(git diff *)",
        "Bash(git status *)",
        "PowerShell(pytest *)",
        "PowerShell(alembic *)",
        "PowerShell(git add *)",
        "PowerShell(git commit *)",
        "PowerShell(git diff *)",
        "PowerShell(git status *)",
    ]


def test_allowed_tools_nao_inclui_edit_como_entrada_inteira() -> None:
    """Issue #74: uma entrada `"Edit"` sem especificador blinda
    (`CanUseToolShadowedWarning`) `can_use_tool` E pre-aprova qualquer
    caminho incondicionalmente - foi essa entrada que permitiu o vazamento
    das issues #59/#69/#70. A entrada escopada `"Edit(**)"` (com
    especificador real, nao `""`/`"*"`) e o que efetivamente restringe ao
    `cwd` da invocacao no motor de regras do proprio CLI - confirmado
    contra o SDK real com um espiao no callback (ver docstring de
    `_make_deny_out_of_scope_tools`)."""
    assert "Edit" not in ALLOWED_TOOLS
    assert "Edit(**)" in ALLOWED_TOOLS


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


def _call_deny(tool_name: str, input_data: dict, cwd: str = "."):
    deny = _make_deny_out_of_scope_tools(cwd)
    return anyio.run(deny, tool_name, input_data, None)


@pytest.mark.parametrize("tool_name", ["Bash", "PowerShell"])
def test_deny_bloqueia_git_push(tool_name: str) -> None:
    result = _call_deny(tool_name, {"command": "git push origin main"})
    assert type(result).__name__ == "PermissionResultDeny"


@pytest.mark.parametrize("tool_name", ["Bash", "PowerShell"])
def test_deny_bloqueia_gh_pr(tool_name: str) -> None:
    result = _call_deny(tool_name, {"command": "gh pr create --title x"})
    assert type(result).__name__ == "PermissionResultDeny"


@pytest.mark.parametrize("tool_name", ["Bash", "PowerShell"])
def test_deny_bloqueia_gh_issue(tool_name: str) -> None:
    result = _call_deny(tool_name, {"command": "gh issue close 1"})
    assert type(result).__name__ == "PermissionResultDeny"


@pytest.mark.parametrize("tool_name", ["Bash", "PowerShell"])
def test_deny_bloqueia_comando_fora_dos_padroes_permitidos(tool_name: str) -> None:
    result = _call_deny(tool_name, {"command": "rm -rf /"})
    assert type(result).__name__ == "PermissionResultDeny"


@pytest.mark.parametrize("tool_name", ["Bash", "PowerShell"])
def test_deny_permite_comando_com_padrao_permitido(tool_name: str) -> None:
    """Issue #76: o callback (`can_use_tool`) e defesa-em-profundidade - a
    protecao real sob `permission_mode="dontAsk"` e a entrada escopada em
    `ALLOWED_TOOLS`, resolvida pelo motor de regras do proprio CLI antes
    deste callback ser consultado (mesmo padrao ja confirmado para
    `Edit(**)` na #74). Este teste cobre a logica do callback em si -
    a cobertura de que a entrada do `ALLOWED_TOOLS` de fato evita a
    negacao real do CLI para `PowerShell` esta no teste de integracao
    `tests/integration/test_powershell_local_commit.py`."""
    for command in ["pytest --cov", "alembic upgrade head", "git add .", "git commit -m x", "git diff --stat", "git status"]:
        result = _call_deny(tool_name, {"command": command})
        assert type(result).__name__ == "PermissionResultAllow", f"deveria permitir: {command}"


def test_deny_permite_read_e_edit() -> None:
    assert type(_call_deny("Read", {"file_path": "x.py"})).__name__ == "PermissionResultAllow"
    assert type(_call_deny("Edit", {"file_path": "x.py"})).__name__ == "PermissionResultAllow"


def test_deny_bloqueia_edit_fora_do_cwd_isolado(tmp_path: Path) -> None:
    """Issue #74: reproduz o vazamento observado nas issues #59/#69/#70 da
    janela de validacao - o modelo tenta editar um caminho absoluto fora do
    `cwd` isolado passado a `invoke_sdk`. Antes da correcao, `Edit` era
    permitido incondicionalmente e essa tentativa passava."""
    allowed_root = tmp_path / "nested-simulando-clone-isolado"
    outer_dir = tmp_path / "outer-simulando-working-tree-real"
    allowed_root.mkdir()
    outer_dir.mkdir()
    outside_file = outer_dir / "arquivo.py"
    outside_file.write_text("", encoding="utf-8")

    result = _call_deny("Edit", {"file_path": str(outside_file)}, cwd=str(allowed_root))

    assert type(result).__name__ == "PermissionResultDeny"


def test_deny_permite_edit_com_caminho_absoluto_dentro_do_cwd_isolado(tmp_path: Path) -> None:
    allowed_root = tmp_path / "nested-simulando-clone-isolado"
    allowed_root.mkdir()
    inside_file = allowed_root / "subpasta" / "arquivo.py"
    inside_file.parent.mkdir()
    inside_file.write_text("", encoding="utf-8")

    result = _call_deny("Edit", {"file_path": str(inside_file)}, cwd=str(allowed_root))

    assert type(result).__name__ == "PermissionResultAllow"


def test_deny_bloqueia_edit_com_caminho_relativo_que_escapa_do_cwd_via_dotdot(tmp_path: Path) -> None:
    allowed_root = tmp_path / "nested-simulando-clone-isolado"
    outer_dir = tmp_path / "outer-simulando-working-tree-real"
    allowed_root.mkdir()
    outer_dir.mkdir()
    (outer_dir / "arquivo.py").write_text("", encoding="utf-8")

    result = _call_deny("Edit", {"file_path": "../outer-simulando-working-tree-real/arquivo.py"}, cwd=str(allowed_root))

    assert type(result).__name__ == "PermissionResultDeny"


def test_deny_bloqueia_edit_sem_file_path() -> None:
    result = _call_deny("Edit", {})
    assert type(result).__name__ == "PermissionResultDeny"


def test_invoke_sdk_usa_cwd_da_chamada_para_o_callback_de_permissao(tmp_path: Path) -> None:
    """Verifica de ponta a ponta que `invoke_sdk` monta o callback vinculado
    ao `cwd` recebido (nao a um cwd fixo/global) - captura o `can_use_tool`
    passado a `ClaudeAgentOptions` e confirma que ele nega um caminho fora
    do `cwd` desta chamada especifica."""
    allowed_root = tmp_path / "nested"
    outer_dir = tmp_path / "outer"
    allowed_root.mkdir()
    outer_dir.mkdir()
    outside_file = outer_dir / "arquivo.py"
    outside_file.write_text("", encoding="utf-8")

    captured_options = {}

    async def _spy_query(*, prompt, options):
        captured_options["options"] = options
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

    with patch("agent_local.sdk_invocation.query", _spy_query):
        invoke_sdk("prompt", cwd=str(allowed_root), model="m", max_turns=1, timeout_seconds=5.0)

    can_use_tool = captured_options["options"].can_use_tool
    result = anyio.run(can_use_tool, "Edit", {"file_path": str(outside_file)}, None)
    assert type(result).__name__ == "PermissionResultDeny"


def test_deny_bloqueia_ferramentas_fora_do_escopo() -> None:
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


def test_invoke_sdk_retorna_custo_e_duracao_do_result_message() -> None:
    """Issue #80: `total_cost_usd` e `duration_ms` do `ResultMessage` do SDK
    precisam sobreviver ate o `SDKInvocationResult` retornado, para que
    quem persiste a decisao (gate.py/polling.py) tenha acesso a eles - antes
    so `total_cost_usd` era capturado e nada de duracao."""

    async def _spy_query(*, prompt, options):
        yield ResultMessage(
            subtype="success",
            duration_ms=4321,
            duration_api_ms=4000,
            is_error=False,
            num_turns=2,
            session_id="s2",
            total_cost_usd=0.42,
            result="ok",
        )

    with patch("agent_local.sdk_invocation.query", _spy_query):
        result = invoke_sdk("prompt", cwd=".", model="m", max_turns=1, timeout_seconds=5.0)

    assert result.total_cost_usd == 0.42
    assert result.duration_ms == 4321
    assert result.session_id == "s2"


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
