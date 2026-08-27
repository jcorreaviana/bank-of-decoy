import json
from unittest.mock import MagicMock, patch

from agent_local.github_client import Issue, create_pr, is_issue_open, list_candidate_issues, view_issue


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


def test_create_pr_retorna_numero_e_url() -> None:
    with patch(
        "agent_local.github_client.subprocess.run",
        return_value=_mock_run("https://github.com/x/y/pull/25\n"),
    ):
        pr_number, url = create_pr(title="t", body="b", base="main", head="branch", cwd=".")

    assert pr_number == 25
    assert url == "https://github.com/x/y/pull/25"
