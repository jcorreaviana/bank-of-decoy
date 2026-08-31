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
ESCOPADAS (ex. `"Bash(pytest *)"`) continuam caindo no callback. Para
`Read` isso e inofensivo (permitido incondicionalmente de qualquer forma),
mas e o motivo de nunca colocar um `"Bash"` (sem escopo) em `ALLOWED_TOOLS`
- isso desativaria a checagem de push/PR para TODO comando Bash.

## Issue #74 - achado real MAIOR que o esperado (descoberto testando contra
## o SDK real, com um spy no callback - nao por leitura de codigo/docs)

Ate a correcao da #74, `"Edit"` estava em `ALLOWED_TOOLS` como entrada
INTEIRA - blindava `can_use_tool` para TODO `Edit`, e foi exatamente por
isso que o modelo conseguiu editar fora do `cwd` isolado nas issues
#59/#69/#70 (ver `docs/relatorio-janela-fase2b.md`, secao 11.2): nada
nunca checava o caminho.

A correcao obvia pareceria ser "tirar `Edit` de `ALLOWED_TOOLS` para cair
no callback" (mesma receita que ja funciona para `Bash`/`Grep`/`Glob`).
**Isso NAO funciona na pratica** - testado diretamente com um wrapper-espiao
em volta de `can_use_tool` (nao só lido, chamado de verdade 3x contra o SDK
real): com `permission_mode="dontAsk"` e `Edit` AUSENTE de `ALLOWED_TOOLS`,
toda tentativa de `Edit` (mesmo dentro do `cwd`, uma edicao legitima) foi
negada com a mensagem generica `"don't ask mode" negou a permissão` -
**e o callback nunca foi invocado** (o print do espiao nunca apareceu).
`dontAsk` significa literalmente "nega se nao estiver pre-aprovado"
(`claude_agent_sdk/types.py`, docstring de `permission_mode`) - e para as
categorias de ferramenta que o CLI empacotado conhece nativamente
(`Read`/`Edit`/`Write`/`Bash`), essa decisao de pre-aprovacao acontece
inteiramente dentro do subprocess CLI, contra o `allowed_tools` configurado,
ANTES de qualquer chance de `can_use_tool` ser consultado - confirmado para
`Edit` com `ALLOWED_TOOLS` vazio (negacao sem callback), com `"Edit"` inteiro
(aprovacao sem callback) e com `"Edit(**)"` escopado (decisao correta -
nega fora do `cwd`, permite dentro - AINDA sem callback). Ou seja: para
`Edit` sob `dontAsk`, `can_use_tool` nunca e a "trava de verdade" - e a
premissa original deste modulo (linhas acima, sobre `git push`/`gh pr`)
pode ter a mesma limitacao para `Bash`, mas isso fica como investigacao
futura, fora do escopo da #74 (nao alterei o mecanismo de `Bash` aqui).

**A protecao que REALMENTE funciona para `Edit`** (confirmada com o mesmo
tipo de teste direto - edicao legitima dentro do `cwd`, tentativa com
caminho absoluto fora do `cwd`, e tentativa com `../` relativo escapando do
`cwd`, as 3 rodadas contra o SDK real): a entrada ESCOPADA `"Edit(**)"` em
`ALLOWED_TOOLS`. Por ser um especificador real (nao `""`/`"*"`), o CLI
resolve o glob `**` relativo ao `cwd` desta invocacao (`ClaudeAgentOptions`)
e so pre-aprova caminhos que caem dentro dele - qualquer coisa fora (caminho
absoluto ou `../` relativo) e negada pelo proprio motor de regras do CLI,
sem depender do callback Python em momento algum.

A checagem de caminho em `_make_deny_out_of_scope_tools` (abaixo) foi
mantida mesmo assim - nao e a protecao efetiva hoje (confirmado que o
callback nao roda para `Edit`), mas e barata, documenta explicitamente a
intencao de escopo pedida pela issue #74, e vira a protecao real de
imediato se uma versao futura do CLI parar de blindar entradas escopadas
deste jeito (o comportamento de shadowing e do binario empacotado, fora do
controle deste repositorio, e pode mudar sem aviso em uma atualizacao de
dependencia).

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
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

import anyio
from claude_agent_sdk import (
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
    query,
)

logger = logging.getLogger(__name__)

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
    "Edit(**)",
    "Bash(pytest *)",
    "Bash(alembic *)",
    "Bash(git add *)",
    "Bash(git commit *)",
    "Bash(git diff *)",
    "Bash(git status *)",
]
"""Documenta o escopo pretendido (issue #16) - mas, ao contrario do resto
deste modulo, `"Edit(**)"` especificamente NAO E so metadado: e a protecao
de verdade contra edicao fora do `cwd` isolado (issue #74, ver docstring
do modulo para o achado completo, testado 3x contra o SDK real com um
espiao no callback). `**` e resolvido pelo CLI relativo ao `cwd` desta
invocacao (`ClaudeAgentOptions(cwd=cwd)`) - so pre-aprova caminhos dentro
dele, e sob `permission_mode="dontAsk"` ("nega se nao pre-aprovado") isso
vira uma negacao real para qualquer coisa fora, absoluta ou via `../`.

Deliberadamente NAO e `"Edit"` sem escopo: essa forma (usada antes da #74)
e um especificador "inteiro" que blinda (shadow) `can_use_tool` E
pre-aprova qualquer caminho incondicionalmente - foi exatamente essa
entrada que permitiu o vazamento observado nas issues #59/#69/#70."""

_ALLOWED_BASH_PREFIXES = ("pytest", "alembic", "git add", "git commit", "git diff", "git status")
_FORBIDDEN_BASH_SUBSTRINGS = ("git push", "gh pr", "gh issue")


def _resolve_within_cwd(file_path: str, allowed_root: Path) -> Path | None:
    """Resolve `file_path` (absoluto ou relativo) contra `allowed_root` e
    devolve o caminho absoluto resolvido SE ele cair dentro do prefixo de
    `allowed_root` - devolve None caso contrario (fora do escopo, ou
    caminho invalido). Whitelist de prefixo (achado da issue #74, mesmo
    principio ja aplicado em `_ALLOWED_ENV_PASSTHROUGH` pela #66): nao
    tentamos reconhecer padroes de caminho "perigosos" (blacklist) - so
    aceitamos o que cai dentro da raiz isolada conhecida."""
    candidate = Path(file_path)
    if not candidate.is_absolute():
        candidate = allowed_root / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except OSError:
        return None
    if resolved == allowed_root or resolved.is_relative_to(allowed_root):
        return resolved
    return None


def _make_deny_out_of_scope_tools(cwd: str):
    """Fabrica o callback `can_use_tool` vinculado ao `cwd` isolado desta
    invocacao especifica de `invoke_sdk`.

    Precisa ser uma fabrica (closure), nao uma funcao module-level fixa
    como antes: `ToolPermissionContext` (o `_context` recebido pelo
    callback) nao carrega o `cwd` da chamada - so chega como argumento
    normal a `invoke_sdk` (`claude_agent_sdk/types.py::ToolPermissionContext`,
    confirmado por leitura direta do pacote instalado, sem campo de cwd).
    Por isso o unico jeito de o callback saber qual e o cwd isolado desta
    execucao e capturar via closure no momento em que `invoke_sdk` monta
    `ClaudeAgentOptions`.

    Achado real (issue #74, auditoria da janela de validacao Fase 2b,
    `docs/relatorio-janela-fase2b.md` secao 11.2): mesmo sem o vazamento de
    variavel de ambiente que a #66 corrigiu (sessao IDE anexada), o proprio
    modelo pode decidir editar um caminho absoluto fora do `cwd` passado -
    nada aqui impedia isso antes, `Edit` era permitido incondicionalmente.
    3 de 10 issues da janela (#59, #69, #70) vazaram edicoes reais para a
    working tree do operador por esse canal.

    IMPORTANTE (achado adicional da propria correcao, ver docstring do
    modulo): sob `permission_mode="dontAsk"`, o branch de `Edit` abaixo NAO
    e hoje a protecao que efetivamente bloqueia - `"Edit(**)"` em
    `ALLOWED_TOOLS` e quem faz isso, no motor de regras do proprio CLI,
    antes deste callback ser sequer consultado (confirmado com um espiao
    em volta desta funcao contra o SDK real - o print de invocacao nunca
    aparece para `Edit`). O branch abaixo fica mesmo assim como
    defesa-em-profundidade barata e documentacao explicita do escopo
    pretendido (pedido literal da issue #74) - e volta a ser a protecao
    real se uma atualizacao futura do CLI parar de blindar `"Edit(**)"`."""
    allowed_root = Path(cwd).resolve()

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

        if tool_name == "Read":
            return PermissionResultAllow(updated_input=input_data)

        if tool_name == "Edit":
            file_path = input_data.get("file_path")
            if not file_path or _resolve_within_cwd(file_path, allowed_root) is None:
                logger.warning(
                    "Edit fora do cwd isolado negado (issue #74) - vazamento de isolamento evitado.",
                    extra={"context": {"file_path": file_path, "allowed_root": str(allowed_root)}},
                )
                return PermissionResultDeny(
                    message=(
                        f"Edit em '{file_path}' esta fora do cwd isolado desta execucao "
                        f"('{allowed_root}') - negado para evitar vazamento de isolamento "
                        "(issue #74, mesma classe de falha da #66 por canal diferente)."
                    ),
                    interrupt=False,
                )
            return PermissionResultAllow(updated_input=input_data)

        return PermissionResultDeny(
            message=f"Ferramenta '{tool_name}' fora do escopo desta execucao (permitido: Read, Edit, Bash com padroes de teste/git local).",
            interrupt=False,
        )

    return _deny_out_of_scope_tools


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
        can_use_tool=_make_deny_out_of_scope_tools(cwd),
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
