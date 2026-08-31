"""Teste de integracao REAL (issue #76) - reproduz contra o SDK de verdade
(sem mock) o bug relatado: neste ambiente Windows, o CLI empacotado
registra "PowerShell" como uma ferramenta de shell separada de "Bash"
(confirmado em `SystemMessage(subtype="init").data["tools"]`, listadas
lado a lado). Antes desta correcao, `ALLOWED_TOOLS` (`sdk_invocation.py`)
so tinha entradas `"Bash(...)"` - qualquer `git add`/`git commit` que o
modelo decidisse rodar via `PowerShell` nao correspondia a nenhuma
entrada de `allowed_tools`, caindo no comportamento padrao "ask" do motor
de regras do proprio CLI, que sob `permission_mode="dontAsk"` vira
negacao imediata ANTES de `can_use_tool` ser sequer consultado - mesma
mecanica ja documentada para `Edit` na issue #74, agora confirmada
tambem para o par Bash/PowerShell (ver docstring de `sdk_invocation.py`).

## Por que este teste vive fora de tests/unit/

Mesma razao do `test_isolation_leak.py` (#66/#74): faz uma chamada REAL
ao Claude Agent SDK (custa uso de API de verdade, depende de rede e da
sessao ja autenticada na maquina). Por isso NAO roda com
`pytest tests/unit/` nem faz parte do `/fecha-issue` automatico - precisa
ser rodado explicitamente:

    cd agent-local && .venv/Scripts/python.exe -m pytest tests/integration/test_powershell_local_commit.py -v
"""

import subprocess
from pathlib import Path

import anyio
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    ToolUseBlock,
    query,
)

from agent_local.sdk_invocation import ALLOWED_TOOLS, _make_deny_out_of_scope_tools, _minimal_subprocess_env


def _run_git_repo_prompt(cwd: Path, prompt: str, max_turns: int = 6, timeout: float = 120.0) -> tuple[list, list]:
    options = ClaudeAgentOptions(
        model="claude-sonnet-5",
        effort="medium",
        permission_mode="dontAsk",
        allowed_tools=ALLOWED_TOOLS,
        can_use_tool=_make_deny_out_of_scope_tools(str(cwd)),
        max_turns=max_turns,
        cwd=str(cwd),
    )

    async def _run() -> tuple[list, list]:
        tool_calls: list = []
        denials: list = []
        with _minimal_subprocess_env():
            with anyio.fail_after(timeout):
                async for message in query(prompt=prompt, options=options):
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, ToolUseBlock):
                                tool_calls.append((block.name, block.input.get("command")))
                    if isinstance(message, ResultMessage):
                        denials.extend(message.permission_denials or [])
        return tool_calls, denials

    return anyio.run(_run)


def _init_repo_with_pending_change(repo_dir: Path) -> None:
    subprocess.run(["git", "init", "-q", str(repo_dir)], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "agent-local-test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "agent-local-test"], check=True)
    (repo_dir / "file.txt").write_text("hello\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_dir), "add", "file.txt"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-q", "-m", "initial"], check=True)
    with (repo_dir / "file.txt").open("a", encoding="utf-8") as f:
        f.write("pending change\n")


def _last_commit_message(repo_dir: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_dir), "log", "-1", "--pretty=%s"], check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def test_commit_local_via_powershell_funciona_de_ponta_a_ponta(tmp_path: Path) -> None:
    """Issue #76: reproduz o cenario exato reportado - o modelo escolhe a
    ferramenta PowerShell (nao Bash) para rodar git add + git commit sobre
    uma mudanca pendente real."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_repo_with_pending_change(repo_dir)

    prompt = (
        "Voce esta num repositorio git em cwd, com uma mudanca pendente em file.txt "
        "(rode git status para confirmar). Use a ferramenta PowerShell (nao Bash) para "
        "commitar localmente: git add file.txt seguido de "
        "git commit -m 'commit via powershell issue 76'. Nao faca mais nada."
    )
    tool_calls, denials = _run_git_repo_prompt(repo_dir, prompt)

    assert any(name == "PowerShell" for name, _ in tool_calls), (
        f"o modelo nao tentou usar a ferramenta PowerShell nesta rodada (nao reproduz o cenario "
        f"da issue): {tool_calls}"
    )
    assert denials == [], f"comando dentro do escopo permitido foi negado indevidamente: {denials}"
    assert _last_commit_message(repo_dir) == "commit via powershell issue 76", (
        "o commit local nao foi concluido - regressao da issue #76"
    )


def test_git_push_via_powershell_continua_negado(tmp_path: Path) -> None:
    """Confirma que a correcao nao ampliou o escopo alem do pretendido -
    git push continua fora de ALLOWED_TOOLS tambem para a ferramenta
    PowerShell, negado pelo mesmo mecanismo (motor de regras nativo do
    CLI sob permission_mode="dontAsk")."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _init_repo_with_pending_change(repo_dir)

    prompt = (
        "Use a ferramenta PowerShell para rodar exatamente: "
        "git push origin main --dry-run. So isso, relate o resultado e pare - "
        "nao tente nenhuma ferramenta alternativa se for negado."
    )
    tool_calls, denials = _run_git_repo_prompt(repo_dir, prompt, max_turns=4, timeout=90.0)

    assert any(name == "PowerShell" and cmd and "push" in cmd for name, cmd in tool_calls), (
        f"o modelo nao tentou o git push via PowerShell nesta rodada (nao reproduz o cenario "
        f"de escopo negado): {tool_calls}"
    )
    assert any(d.get("tool_name") == "PowerShell" for d in denials), (
        f"git push via PowerShell deveria continuar negado: denials={denials}, tool_calls={tool_calls}"
    )
