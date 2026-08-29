import json
import subprocess
from unittest.mock import MagicMock, patch

from agent_local.github_client import (
    Issue,
    add_issue_label,
    create_pr,
    is_issue_open,
    list_candidate_issues,
    remove_issue_label,
    unassign_self,
    view_issue,
)


def _mock_run(stdout: str) -> MagicMock:
    result = MagicMock()
    result.stdout = stdout
    return result


def test_list_candidate_issues_parseia_json_do_gh() -> None:
    payload = json.dumps(
        [
            {
                "number": 16,
                "title": "[FASE 4] Agente local",
                "body": "corpo",
                "labels": [{"name": "business-story"}],
                "assignees": [],
                "url": "https://github.com/x/y/issues/16",
            }
        ]
    )
    with patch("agent_local.github_client.subprocess.run", return_value=_mock_run(payload)):
        issues = list_candidate_issues()

    assert issues == [
        Issue(
            number=16,
            title="[FASE 4] Agente local",
            body="corpo",
            labels=["business-story"],
            assignees=[],
            url="https://github.com/x/y/issues/16",
        )
    ]


def test_view_issue_parseia_json_do_gh() -> None:
    payload = json.dumps(
        {
            "number": 17,
            "title": "[BUG] x",
            "body": "y",
            "labels": [{"name": "bug"}],
            "assignees": [{"login": "agent-local"}],
            "url": "https://github.com/x/y/issues/17",
        }
    )
    with patch("agent_local.github_client.subprocess.run", return_value=_mock_run(payload)):
        issue = view_issue(17)

    assert issue.number == 17
    assert issue.assignees == ["agent-local"]


def test_is_issue_open_true_quando_state_open() -> None:
    with patch("agent_local.github_client.subprocess.run", return_value=_mock_run('{"state": "OPEN"}')):
        assert is_issue_open(1) is True


def test_is_issue_open_false_quando_state_closed() -> None:
    with patch("agent_local.github_client.subprocess.run", return_value=_mock_run('{"state": "CLOSED"}')):
        assert is_issue_open(1) is False


def test_is_issue_open_false_quando_numero_nao_existe_no_github() -> None:
    # Achado real na issue #50: secao "Dependencias" cita numeros de issue
    # (#11, #9) que nao existem mais no GitHub. `gh issue view` retorna
    # codigo de saida != 0 nesse caso - antes derrubava pick_candidate_issue
    # (fora do try/except de process_issue), agora e tratado como
    # "nao bloqueia" em vez de propagar a excecao.
    error = subprocess.CalledProcessError(
        returncode=1, cmd=["gh", "issue", "view", "11", "--json", "state"], stderr="GraphQL: Could not resolve to an issue"
    )
    with patch("agent_local.github_client.subprocess.run", side_effect=error):
        assert is_issue_open(11) is False


def test_create_pr_retorna_numero_e_url() -> None:
    with patch(
        "agent_local.github_client.subprocess.run",
        return_value=_mock_run("https://github.com/x/y/pull/25\n"),
    ):
        pr_number, url = create_pr(title="t", body="b", base="main", head="branch", cwd=".")

    assert pr_number == 25
    assert url == "https://github.com/x/y/pull/25"


def test_unassign_self_remove_o_proprio_usuario() -> None:
    with patch("agent_local.github_client.subprocess.run", return_value=_mock_run("")) as mock_run:
        unassign_self(42)

    args = mock_run.call_args.args[0]
    assert args == ["gh", "issue", "edit", "42", "--remove-assignee", "@me"]


def test_add_issue_label() -> None:
    with patch("agent_local.github_client.subprocess.run", return_value=_mock_run("")) as mock_run:
        add_issue_label(42, "agent-stuck")

    args = mock_run.call_args.args[0]
    assert args == ["gh", "issue", "edit", "42", "--add-label", "agent-stuck"]


def test_remove_issue_label() -> None:
    with patch("agent_local.github_client.subprocess.run", return_value=_mock_run("")) as mock_run:
        remove_issue_label(42, "agent-retry-1")

    args = mock_run.call_args.args[0]
    assert args == ["gh", "issue", "edit", "42", "--remove-label", "agent-retry-1"]
