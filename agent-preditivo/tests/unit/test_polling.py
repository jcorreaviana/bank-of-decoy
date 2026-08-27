from unittest.mock import patch

from agent_preditivo.polling import run_cycle


def test_run_cycle_erro_e_notificado_e_nao_propaga() -> None:
    """Regressao critica: um erro num ciclo (Ollama fora do ar, etc.) nao
    pode derrubar o loop de polling - deve ser notificado e o processo
    segue vivo para o proximo ciclo."""
    with (
        patch("agent_preditivo.polling.run_bug_cycle", side_effect=RuntimeError("Ollama indisponível")),
        patch("agent_preditivo.polling.notify_agent_error") as mock_notify,
    ):
        run_cycle(include_opportunity=False)  # nao deve levantar

    mock_notify.assert_called_once()
    assert mock_notify.call_args.args[0] == "agent-preditivo"
    assert "Ollama indisponível" in mock_notify.call_args.args[1]


def test_run_cycle_sem_erro_nao_notifica() -> None:
    with (
        patch("agent_preditivo.polling.run_bug_cycle", return_value=[]),
        patch("agent_preditivo.polling.notify_agent_error") as mock_notify,
    ):
        run_cycle(include_opportunity=False)

    mock_notify.assert_not_called()
