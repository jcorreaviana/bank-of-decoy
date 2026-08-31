"""Invocacao do Claude Agent SDK (specs/business/14-agente-local.md, passo
4) - o unico ponto do agente local que chama um LLM para gerar codigo.

## ALLOWED_TOOLS NAO E UMA TRAVA DE SEGURANCA (achado real, nao suposicao)

Testado diretamente contra o SDK real (nao só lido na documentação): com
`permission_mode="dontAsk"` e `allowed_tools` restrito a Read/Edit/Bash com
poucos padroes, o modelo AINDA CONSEGUIU chamar `Grep`, `Glob` e `Bash` com
comandos arbitrarios (`git log --all -p`, `find`, `grep -r`) sem nenhuma
negacao (`permission_denials: []` no resultado). `allowed_tools` sozinho e
so uma lista de "nao precisa perguntar" quando ha um humano interativo -
NAO um allowlist estrito que bloqueia o resto.

A trava que REALMENTE bloqueia, confirmada pelo mesmo tipo de teste direto:
o callback `can_use_tool` (`ClaudeAgentOptions(can_use_tool=...)`). Com ele,
uma tentativa real de `git push origin main --dry-run` e `gh pr list` foi
efetivamente NEGADA (o modelo recebeu a negacao e nao tentou contornar).
Por isso este modulo usa `can_use_tool` como o gate de verdade -
`allowed_tools` fica so como metadado/documentacao da intencao de escopo,
nao a protecao em si.

Nuance adicional (o proprio SDK avisa isso em runtime,
`CanUseToolShadowedWarning`): uma entrada de `allowed_tools` que libera uma
ferramenta INTEIRA (ex. `"Read"`, `"Edit"`) faz o SDK auto-aprovar sem
sequer consultar `can_use_tool` para essa ferramenta - so entradas
ESCOPADAS (ex. `"Bash(pytest *)"`) continuam caindo no callback. Aqui isso
e inofensivo (Read/Edit sao mesmo permitidos por `_deny_out_of_scope_tools`),
mas e o motivo de nunca colocar um `"Bash"` (sem escopo) em `ALLOWED_TOOLS`
- isso desativaria a checagem de push/PR para TODO comando Bash.

## Racional de separacao de responsabilidade (por que push/PR ficam FORA daqui)

`_deny_out_of_scope_tools` nega explicitamente qualquer `Bash` cujo comando
contenha `git push`, `gh pr` ou `gh issue`, e nega qualquer ferramenta que
nao seja Read/Edit/Bash(com um dos padroes permitidos). Isso e deliberado:
o gate de aprovacao (risk_score.py) roda depois que esta funcao retorna, em
codigo deterministico no wrapper Python (gate.py/polling.py) - nunca dentro
do raciocinio do modelo. Um LLM que pudesse decidir sozinho subir o proprio
codigo tornaria o gate decorativo. Com `can_use_tool` negando de verdade
(confirmado por teste, nao por documentacao), o modelo fisicamente nao
consegue `git push`/`gh pr create` mesmo que "decida" que o codigo esta
pronto - so o codigo deste modulo tem esse poder.

## Autenticacao

Confirmado por teste real (docs/escopo-arquitetura.md v22): o SDK
(`claude_agent_sdk`, que envolve o CLI `@anthropic-ai/claude-code`)
autentica pela sessao ja logada do plano Pro nesta maquina
(`~/.claude/.credentials.json`), sem exigir `ANTHROPIC_API_KEY` separada -
a exigencia de API key na documentacao oficial e para produtos
multi-usuario de terceiros, nao automacao individual sobre o proprio
projeto.
"""

import contextlib
import os
import re
from dataclasses import dataclass

import anyio
from claude_agent_sdk import (
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    query,
)

_ALLOWED_ENV_PASSTHROUGH = (
    "PATH",
    "SYSTEMROOT",  # Windows: exigido por varias APIs do SO (winsock, crypto) mesmo sem uso direto daqui
    "USERPROFILE",  # Windows: resolve ~ para ~/.claude/.credentials.json (autenticacao, ver docstring do modulo)
    "HOMEDRIVE",
    "HOMEPATH",
    "HOME",  # equivalente POSIX de USERPROFILE, para portabilidade futura
    "TEMP",
    "TMP",
    "APPDATA",
    "LOCALAPPDATA",
    "COMSPEC",
    "PATHEXT",
)
"""Lista positiva (achado real, issue de vazamento de isolamento): o SDK
(`subprocess_cli.py`, `_connect`) monta o ambiente do subprocess como
`{**inherited_env, **options.env}` - ou seja, `ClaudeAgentOptions(env=...)`
so SOBREPOE chaves especificas, nunca substitui `os.environ` herdado por
completo. Uma tentativa de "whitelist" so via `options.env` nao funcionaria
por esse motivo - `_minimal_subprocess_env()` abaixo e a unica forma real
de garantir que so estas variaveis cheguem ao subprocess, reduzindo o
`os.environ` do PROPRIO processo chamador (so durante a chamada, ver
`invoke_sdk`). Deliberadamente NAO e uma lista negativa de variaveis
conhecidas por vazar (`CLAUDE_CODE_MESSAGING_SOCKET` etc.) - isso reabriria
o mesmo buraco no dia em que uma variavel nova aparecer no ambiente."""


@contextlib.contextmanager
def _minimal_subprocess_env():
    """Reduz `os.environ` do processo chamador a `_ALLOWED_ENV_PASSTHROUGH`
    só durante o bloco, restaurando tudo depois (inclusive em caso de
    excecao). Escopo deliberadamente estreito - so ao redor da chamada ao
    SDK, nunca o processo inteiro do daemon: `github_client`/`git_ops`
    tambem rodam subprocess (`gh`, `git`) mas nao fazem parte da superficie
    deste vazamento (nao spawnam o CLI da Claude Agent SDK), e podem
    depender de outras variaveis do ambiente normal.

    Achado real: um daemon do agent-local lancado como subtarefa em
    background de uma sessao interativa do Claude Code dentro do VS Code
    herda variaveis que identificam essa sessao para o IDE
    (`CLAUDE_CODE_MESSAGING_SOCKET`/`CLAUDE_CODE_MESSAGING_TOKEN`/
    `CLAUDE_CODE_SESSION_ID`, entre outras) - o CLI empacotado que o SDK
    invoca (`claude_agent_sdk/_bundled/claude.exe`) contem logica para se
    conectar a essa sessao IDE quando essas variaveis estao presentes,
    fazendo com que Read/Edit (e possivelmente outras ferramentas)
    resolvam caminhos contra a workspace root do IDE anexado, e nao contra
    o `cwd` explicitamente passado a `ClaudeAgentOptions`. Reproduzido de
    forma controlada e deterministica (arquivo-marcador distinto no clone
    isolado vs. na working tree externa) - ver
    `tests/integration/test_isolation_leak.py`."""
    original = dict(os.environ)
    try:
        os.environ.clear()
        for key in _ALLOWED_ENV_PASSTHROUGH:
            if key in original:
                os.environ[key] = original[key]
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)

ALLOWED_TOOLS = [
    "Read",
    "Edit",
    "Bash(pytest *)",
    "Bash(alembic *)",
    "Bash(git add *)",
    "Bash(git commit *)",
    "Bash(git diff *)",
    "Bash(git status *)",
]
"""Documenta o escopo pretendido (issue #16) - NAO e a trava de seguranca
em si, ver docstring do modulo. Mantido tambem como argumento real de
`ClaudeAgentOptions` porque reduz prompts/ruido quando ha supervisao
interativa, mas `can_use_tool` e quem efetivamente bloqueia."""

_ALLOWED_BASH_PREFIXES = ("pytest", "alembic", "git add", "git commit", "git diff", "git status")
_FORBIDDEN_BASH_SUBSTRINGS = ("git push", "gh pr", "gh issue")


async def _deny_out_of_scope_tools(tool_name: str, input_data: dict, _context) -> PermissionResultAllow | PermissionResultDeny:
    if tool_name == "Bash":
        command = input_data.get("command", "")
        if any(forbidden in command for forbidden in _FORBIDDEN_BASH_SUBSTRINGS):
            return PermissionResultDeny(
                message="git push/gh pr/gh issue sao responsabilidade exclusiva do wrapper Python, apos o gate de risco - nunca do modelo.",
                interrupt=False,
            )
        if not command.strip().startswith(_ALLOWED_BASH_PREFIXES):
            return PermissionResultDeny(
                message=f"Comando Bash fora do escopo desta execucao (permitido: {', '.join(_ALLOWED_BASH_PREFIXES)}).",
                interrupt=False,
            )
        return PermissionResultAllow(updated_input=input_data)

    if tool_name in ("Read", "Edit"):
        return PermissionResultAllow(updated_input=input_data)

    return PermissionResultDeny(
        message=f"Ferramenta '{tool_name}' fora do escopo desta execucao (permitido: Read, Edit, Bash com padroes de teste/git local).",
        interrupt=False,
    )


@dataclass(frozen=True)
class SDKInvocationResult:
    success: bool
    result_text: str
    total_cost_usd: float | None
    session_id: str | None
    duration_ms: int | None = None
    """Duracao total da chamada (`ResultMessage.duration_ms`, tempo de
    parede reportado pelo proprio SDK - inclui overhead de subprocess, nao
    so tempo de API) - persistida em `risk_decisions` (issue #80) junto com
    `total_cost_usd`, hoje so disponivel em log/stdout."""


def build_task_prompt(issue_number: int, issue_title: str, issue_body: str, spec_text: str | None) -> str:
    spec_block = f"\n\nSpec de referencia completa:\n{spec_text}" if spec_text else ""
    return (
        f"Implemente a issue #{issue_number} deste repositorio: \"{issue_title}\".\n\n"
        f"Corpo da issue:\n{issue_body}"
        f"{spec_block}\n\n"
        "Implemente exatamente o que a issue pede, seguindo as convencoes ja "
        "estabelecidas no repositorio (specs/tech/). Seu acesso a ferramentas "
        "esta restrito a leitura (Read) e edicao de arquivos JA EXISTENTES "
        "(Edit - nao ha ferramenta de criar arquivo novo, nem Glob/Grep para "
        "buscar arquivos nesta execucao - use os caminhos ja indicados na "
        "issue). NAO tente rodar a suite de testes voce mesmo - isso e feito "
        "separadamente, fora desta execucao, por um wrapper que roda pytest "
        "com cobertura depois que voce termina; nao ha pytest/venv "
        "disponivel neste sandbox e tentar so desperdica turns. Faca commit "
        "local das mudancas (git add + git commit) assim que a edicao "
        "estiver pronta - voce NAO tem acesso a git push nem a comandos gh "
        "(isso e forcado tecnicamente, nao so uma instrucao): nao tente, nao "
        "feche a issue, nao abra PR. Se a issue tiver premissa incorreta "
        "(ex. referenciar algo que nao existe no codigo), NAO invente - pare "
        "e explique o que encontrou, sem fazer commit."
    )


def invoke_sdk(
    prompt: str, cwd: str, model: str, max_turns: int, timeout_seconds: float, effort: str = "medium"
) -> SDKInvocationResult:
    """`timeout_seconds` e obrigatorio (nao tem default) de proposito -
    specs/tech/error-handling.md exige timeout explicito em toda chamada ao
    SDK dentro de `process_issue`, para garantir que o `finally`/`except` do
    ciclo de vida pos-`assign_self` seja alcancado mesmo se o SDK travar sem
    lancar excecao (ex. processo do CLI pendurado). `anyio.fail_after`
    cancela a operacao em andamento e levanta `TimeoutError` mesmo nesse
    caso, ao contrario de so confiar em o SDK eventualmente lancar algo."""
    options = ClaudeAgentOptions(
        model=model,
        effort=effort,
        permission_mode="dontAsk",
        allowed_tools=ALLOWED_TOOLS,
        can_use_tool=_deny_out_of_scope_tools,
        max_turns=max_turns,
        cwd=cwd,
    )

    async def _run() -> SDKInvocationResult:
        result_text = ""
        total_cost_usd = None
        session_id = None
        duration_ms = None
        with anyio.fail_after(timeout_seconds):
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, ResultMessage):
                    result_text = message.result or ""
                    total_cost_usd = message.total_cost_usd
                    session_id = message.session_id
                    duration_ms = message.duration_ms
        return SDKInvocationResult(
            success=bool(result_text),
            result_text=result_text,
            total_cost_usd=total_cost_usd,
            session_id=session_id,
            duration_ms=duration_ms,
        )

    with _minimal_subprocess_env():
        return anyio.run(_run)
