from unittest.mock import patch

from agent_local.dependency_check import extract_dependency_issue_numbers, has_open_dependency

_BODY_COM_DEPENDENCIA = """
## Dependências

Depende da issue #15 (agente preditivo) e da issue #9.
"""

_BODY_SEM_DEPENDENCIA = """
## Dependências

Nenhuma.
"""


def test_extract_dependency_issue_numbers() -> None:
    assert extract_dependency_issue_numbers(_BODY_COM_DEPENDENCIA) == [15, 9]


def test_extract_dependency_issue_numbers_sem_referencia() -> None:
    assert extract_dependency_issue_numbers(_BODY_SEM_DEPENDENCIA) == []


def test_extract_dependency_issue_numbers_secao_ausente() -> None:
    assert extract_dependency_issue_numbers("## Resumo\n\nSem secao.") == []


def test_has_open_dependency_pula_quando_dependencia_aberta() -> None:
    with patch("agent_local.dependency_check.is_issue_open", side_effect=[False, True]):
        assert has_open_dependency(_BODY_COM_DEPENDENCIA) is True


def test_has_open_dependency_segue_quando_todas_fechadas() -> None:
    with patch("agent_local.dependency_check.is_issue_open", return_value=False):
        assert has_open_dependency(_BODY_COM_DEPENDENCIA) is False


def test_has_open_dependency_sem_dependencias_nunca_bloqueia() -> None:
    with patch("agent_local.dependency_check.is_issue_open") as mock_open:
        assert has_open_dependency(_BODY_SEM_DEPENDENCIA) is False
    mock_open.assert_not_called()
