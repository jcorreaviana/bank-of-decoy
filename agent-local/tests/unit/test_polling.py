import logging
from unittest.mock import MagicMock, patch

from agent_local.github_client import Issue
from agent_local.polling import pick_candidate_issue, run_cycle


def _issue(number: int = 42, labels: list[str] | None = None) -> Issue:
    return Issue(
        number=number,
        title="t",
        body="b",
        labels=labels if labels is not None else ["bug"],
        assignees=[],
        url=f"https://github.com/x/y/issues/{number}",
    )


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


def test_pick_candidate_issue_pula_issue_marcada_como_caos() -> None:
    """Regressao critica (specs/business/21-filtro-caos-pipeline-agentes.md):
    issue de bug originada de falha simulada pela camada de caos nao deve
    ser tratada como candidata - nao ha bug de codigo para "corrigir", e o
    unico efeito seria o agente propor mexer no proprio middleware de caos."""
    caos_issue = _issue(number=1, labels=["bug", "chaos-test"])
    issue_real = _issue(number=2, labels=["bug"])
    with (
        patch("agent_local.polling.github_client.list_candidate_issues", return_value=[caos_issue, issue_real]),
        patch("agent_local.polling.has_open_dependency", return_value=False),
    ):
        picked = pick_candidate_issue()

    assert picked is not None
    assert picked.number == 2


def test_pick_candidate_issue_so_com_issues_de_caos_retorna_none() -> None:
    caos_issue = _issue(number=1, labels=["bug", "chaos-test"])
    with (
        patch("agent_local.polling.github_client.list_candidate_issues", return_value=[caos_issue]),
        patch("agent_local.polling.has_open_dependency", return_value=False),
    ):
        assert pick_candidate_issue() is None


def test_pick_candidate_issue_ainda_respeita_dependencia_aberta() -> None:
    caos_issue = _issue(number=1, labels=["bug", "chaos-test"])
    issue_com_dependencia = _issue(number=2, labels=["bug"])
    issue_livre = _issue(number=3, labels=["bug"])
    with (
        patch(
            "agent_local.polling.github_client.list_candidate_issues",
            return_value=[caos_issue, issue_com_dependencia, issue_livre],
        ),
        patch("agent_local.polling.has_open_dependency", side_effect=[True, False]),
    ):
        picked = pick_candidate_issue()

    assert picked is not None
    assert picked.number == 3


def test_run_cycle_sucesso_nao_notifica_erro() -> None:
    with (
        patch("agent_local.polling.pick_candidate_issue", return_value=_issue()),
        patch("agent_local.polling.process_issue", return_value={"issue_number": 42}),
        patch("agent_local.polling.notify_agent_error") as mock_notify,
    ):
        result = run_cycle()

    assert result == {"issue_number": 42}
    mock_notify.assert_not_called()


def test_run_cycle_sem_candidata_loga_info(caplog) -> None:
    """Issue #33: ciclo sem candidata (caminho feliz, nada a fazer) nao
    pode ficar silencioso."""
    with (
        caplog.at_level(logging.INFO, logger="agent_local.polling"),
        patch("agent_local.polling.pick_candidate_issue", return_value=None),
        patch("agent_local.polling.notify_agent_error"),
    ):
        run_cycle()

    messages = [record.message for record in caplog.records]
    assert any("iniciado" in m for m in messages)
    assert any("sem candidata" in m for m in messages)


def test_pick_candidate_issue_loga_motivo_do_skip_por_caos(caplog) -> None:
    caos_issue = _issue(number=1, labels=["bug", "chaos-test"])
    issue_real = _issue(number=2, labels=["bug"])
    with (
        caplog.at_level(logging.INFO, logger="agent_local.polling"),
        patch("agent_local.polling.github_client.list_candidate_issues", return_value=[caos_issue, issue_real]),
        patch("agent_local.polling.has_open_dependency", return_value=False),
    ):
        picked = pick_candidate_issue()

    assert picked is not None and picked.number == 2
    messages = [record.message for record in caplog.records]
    assert any("origem caos" in m.lower() for m in messages)
    assert any("selecionada" in m for m in messages)


def test_pick_candidate_issue_loga_motivo_do_skip_por_dependencia(caplog) -> None:
    issue_com_dependencia = _issue(number=2, labels=["bug"])
    issue_livre = _issue(number=3, labels=["bug"])
    with (
        caplog.at_level(logging.INFO, logger="agent_local.polling"),
        patch(
            "agent_local.polling.github_client.list_candidate_issues",
            return_value=[issue_com_dependencia, issue_livre],
        ),
        patch("agent_local.polling.has_open_dependency", side_effect=[True, False]),
    ):
        pick_candidate_issue()

    messages = [record.message for record in caplog.records]
    assert any("dependência aberta" in m for m in messages)


def test_pick_candidate_issue_loga_quando_nenhuma_candidata(caplog) -> None:
    with (
        caplog.at_level(logging.INFO, logger="agent_local.polling"),
        patch("agent_local.polling.github_client.list_candidate_issues", return_value=[]),
    ):
        assert pick_candidate_issue() is None

    messages = [record.message for record in caplog.records]
    assert any("Nenhuma issue candidata" in m for m in messages)
