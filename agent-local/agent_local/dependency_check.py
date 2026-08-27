"""Verificacao de dependencias (specs/business/14-agente-local.md, passo 2):
le a secao '## Dependencias' do corpo da issue, extrai numeros de issue
referenciados (`#N`), verifica se alguma ainda esta aberta via `gh issue view`.

Formato esperado da secao (mesmo padrao usado em todas as issues do
projeto ate aqui, ex. issue #16: 'Depende da issue #15 (...) e da
infraestrutura...'): texto livre em portugues contendo referencias `#N`.
Uma secao sem nenhum `#N` (ex. 'Nenhuma.') significa sem dependencias.
"""

import re

from agent_local.github_client import is_issue_open

_DEPENDENCIAS_SECTION = re.compile(r"##\s*Depend[êe]ncias\s*\n(.*?)(?:\n##|\Z)", re.DOTALL | re.IGNORECASE)
_ISSUE_REF = re.compile(r"#(\d+)")


def extract_dependency_issue_numbers(issue_body: str) -> list[int]:
    match = _DEPENDENCIAS_SECTION.search(issue_body)
    if not match:
        return []
    section_text = match.group(1)
    return [int(n) for n in _ISSUE_REF.findall(section_text)]


def has_open_dependency(issue_body: str) -> bool:
    """True se qualquer issue referenciada na secao de dependencias ainda
    estiver aberta - candidata deve ser pulada nesse caso."""
    for issue_number in extract_dependency_issue_numbers(issue_body):
        if is_issue_open(issue_number):
            return True
    return False
