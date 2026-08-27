from unittest.mock import MagicMock, patch

from agent_local.github_client import Issue
from agent_local.polling import run_cycle


def _issue(number: int = 42) -> Issue:
    return Issue(number=number, title="t", body="b", labels=["bug"], assignees=[], url="https://github.com/x/y/issues/42")


def test_run_cycle_sem_candidata_retorna_none_sem_notificar() -> None:
    with (
        patch("agent_local.polling.pick_candidate_issue", return_value=None),
        patch("agent_local.polling.notify_agent_error") as mock_notify,
    ):
        result = run_cycle()

    assert result is None
    mock_notify.assert_not_called()


def test_run_cycle_erro_ao_processar_e_notificado_e_nao_propaga() -> None:
    """Regressao critica: um erro processando uma issue (SDK indisponivel,
    falha de rede) nao pode derrubar o loop de polling - deve ser
    notificado e o processo segue vivo para o proximo ciclo."""
    with (
        patch("agent_local.polling.pick_candidate_issue", return_value=_issue()),
        patch("agent_local.polling.process_issue", side_effect=RuntimeError("SDK indisponível")),
        patch("agent_local.polling.notify_agent_error") as mock_notify,
    ):
        result = run_cycle()  # nao deve levantar

    assert result is None
    mock_notify.assert_called_once()
    assert mock_notify.call_args.args[0] == "agent-local"
    assert "SDK indisponível" in mock_notify.call_args.args[1]
    assert mock_notify.call_args.kwargs["context"]["issue"] == "#42"


def test_run_cycle_sucesso_nao_notifica_erro() -> None:
    with (
        patch("agent_local.polling.pick_candidate_issue", return_value=_issue()),
        patch("agent_local.polling.process_issue", return_value={"issue_number": 42}),
        patch("agent_local.polling.notify_agent_error") as mock_notify,
    ):
        result = run_cycle()

    assert result == {"issue_number": 42}
    mock_notify.assert_not_called()
