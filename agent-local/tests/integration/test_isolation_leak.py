"""Teste de regressao PERMANENTE do vazamento de isolamento entre o
subprocess do Claude Agent SDK (invocado por `invoke_sdk`) e a working
tree real do operador.

## Por que este teste vive fora de tests/unit/

Faz uma chamada REAL ao Claude Agent SDK (custa uso de API de verdade,
depende de rede e de autenticacao ja logada na maquina - mesma premissa
de `sdk_invocation.py`, ver sua docstring de autenticacao). Por isso NAO
roda com `pytest tests/unit/` (rapido, so mocks) nem faz parte do
`/fecha-issue` automatico - precisa ser rodado explicitamente:

    cd agent-local && .venv/Scripts/python.exe -m pytest tests/integration/test_isolation_leak.py -v

Mesmo assim e um teste de regressao "permanente" no sentido que importa:
a falha que ele cobre e SILENCIOSA (nenhuma excecao, nenhum log de erro -
so um arquivo editado no lugar errado, achado real ao processar a issue
#55) e so pode ser detectada observando o comportamento real do
subprocess, nao mockando `invoke_sdk`/`query`. Rodar manualmente sempre
que: (a) a versao do `claude_agent_sdk`/CLI empacotado mudar, (b) a forma
de lancar o daemon do agent-local mudar, ou (c) antes de uma janela de
validacao real (issue #54).

## O que o teste prova

`invoke_sdk` roda com `cwd` apontando para um diretorio "nested" (isolado,
simulando `agent-local/workspace/bank-of-decoy`). Existe um segundo
diretorio "outer" (simulando a working tree real do operador) com um
arquivo-marcador de conteudo DIFERENTE. Pede-se para o SDK editar
`ISOLATION_TEST_MARKER.txt`. Sem o fix (`_minimal_subprocess_env` em
`sdk_invocation.py`), esta mesma reproducao editou o arquivo do diretorio
"outer" em vez do "nested" quando rodada de dentro de uma sessao
interativa do Claude Code no VS Code (variaveis de ambiente da sessao IDE
herdadas pelo subprocess - ver docstring de `_minimal_subprocess_env`).
"""

from pathlib import Path

from agent_local.sdk_invocation import invoke_sdk


def test_edicao_do_sdk_fica_isolada_no_cwd_passado_e_nao_vaza_para_outro_diretorio(tmp_path: Path) -> None:
    outer_dir = tmp_path / "outer-simulando-working-tree-real"
    nested_dir = tmp_path / "nested-simulando-clone-isolado"
    outer_dir.mkdir()
    nested_dir.mkdir()

    marker_name = "ISOLATION_TEST_MARKER.txt"
    (outer_dir / marker_name).write_text("OUTER_MARKER_NAO_DEVE_SER_EDITADO\n", encoding="utf-8")
    (nested_dir / marker_name).write_text("NESTED_MARKER_DEVE_SER_EDITADO\n", encoding="utf-8")

    prompt = (
        f"Edite o arquivo {marker_name} (ja existe no diretorio de trabalho atual) "
        "adicionando uma nova linha no final com exatamente o texto: "
        "EDITADO_PELO_TESTE_DE_ISOLACAO. Nao faca mais nada."
    )

    result = invoke_sdk(
        prompt,
        cwd=str(nested_dir),
        model="claude-sonnet-5",
        max_turns=5,
        timeout_seconds=120.0,
    )

    assert result.success, f"SDK nao concluiu: {result.result_text}"

    nested_content = (nested_dir / marker_name).read_text(encoding="utf-8")
    outer_content = (outer_dir / marker_name).read_text(encoding="utf-8")

    assert "EDITADO_PELO_TESTE_DE_ISOLACAO" in nested_content, (
        "a edicao deveria ter acontecido no diretorio isolado (cwd passado a invoke_sdk), "
        f"mas o conteudo continua: {nested_content!r}"
    )
    assert outer_content == "OUTER_MARKER_NAO_DEVE_SER_EDITADO\n", (
        "VAZAMENTO DE ISOLAMENTO: o arquivo do diretorio 'outer' (simulando a working tree "
        f"real do operador) foi alterado: {outer_content!r} - a edicao do SDK nao ficou "
        "restrita ao cwd isolado passado a invoke_sdk."
    )
