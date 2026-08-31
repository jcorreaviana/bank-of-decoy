import logging
from unittest.mock import MagicMock, patch

import pytest

from agent_local.github_client import Issue
from agent_local.polling import (
    AGENT_STUCK_LABEL,
    NO_ACTION_DECISION,
    _current_retry_count,
    pick_candidate_issue,
    process_issue,
    run_cycle,
)
from agent_local.risk_score import RiskFields, RiskScoreResult
from agent_local.sdk_invocation import SDKInvocationResult


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


def _settings(max_consecutive_failures: int = 3) -> MagicMock:
    """`process_issue` so precisa de `max_consecutive_failures` antes de
    `git_ops.ensure_repo_cloned` ser chamado nesses testes (que ja falha de
    proposito) - os demais campos de Settings nunca sao lidos."""
    settings = MagicMock()
    settings.max_consecutive_failures = max_consecutive_failures
    return settings


def _full_settings() -> MagicMock:
    """Settings completo, para testes que percorrem `process_issue` ate o
    ponto de decisao de no-op (diff/coverage/risk), nao so ate a primeira
    falha."""
    settings = MagicMock()
    settings.max_consecutive_failures = 3
    settings.repo_url = "https://github.com/x/y"
    settings.repo_clone_dir = "./workspace"
    settings.model = "claude-sonnet-5"
    settings.max_turns = 50
    settings.sdk_timeout_seconds = 1800.0
    settings.test_database_host = "localhost"
    settings.test_database_port = "5433"
    return settings


def _risk(diff_lines: int) -> RiskScoreResult:
    return RiskScoreResult(
        score=78.0,
        threshold=20.0,
        decision="humano",
        risk_fields=RiskFields(
            category="regra_de_negocio", criticality="critico", category_parsed=False, criticality_parsed=False
        ),
        coverage_fraction=0.0,
        diff_lines=diff_lines,
    )


def _sdk_result(success: bool, result_text: str = "", duration_ms: int | None = None) -> SDKInvocationResult:
    return SDKInvocationResult(
        success=success, result_text=result_text, total_cost_usd=0.05, session_id="session-1", duration_ms=duration_ms
    )


def test_process_issue_diff_lines_zero_com_sdk_sucesso_gera_no_action_needed() -> None:
    """Destino 2 (specs/tech/error-handling.md): SDK concluiu (result_text
    presente) e nao gerou diff - decisao propria em risk_decisions, sem
    push/PR, issue desatribuida com comentario especifico (nao o comentario
    generico de falha do destino 3)."""
    issue = _issue(number=41)
    risk = _risk(diff_lines=0)
    sdk_result = _sdk_result(success=True, result_text="A issue ja esta implementada, nenhuma mudanca necessaria.")

    with (
        patch("agent_local.polling.get_settings", return_value=_full_settings()),
        patch("agent_local.polling.github_client.assign_self"),
        patch("agent_local.polling.git_ops.ensure_repo_cloned", return_value="/tmp/repo"),
        patch("agent_local.polling.git_ops.create_issue_branch", return_value="issue-41"),
        patch("agent_local.polling.invoke_sdk", return_value=sdk_result),
        patch("agent_local.polling.test_runner.get_diff_stat") as mock_diff_stat,
        patch("agent_local.polling.test_runner.detect_affected_services", return_value=[]),
        patch("agent_local.polling.calculate_risk_score", return_value=risk),
        patch("agent_local.polling.agent_ops_db.record_risk_decision") as mock_record,
        patch("agent_local.polling.github_client.comment_issue") as mock_comment,
        patch("agent_local.polling.github_client.close_issue") as mock_close,
        patch("agent_local.polling.github_client.unassign_self") as mock_unassign,
        patch("agent_local.polling.git_ops.delete_local_branch") as mock_delete_branch,
        patch("agent_local.polling.git_ops.push_branch") as mock_push,
        patch("agent_local.polling.open_pull_request") as mock_open_pr,
        patch("agent_local.polling.apply_gate") as mock_apply_gate,
        patch("agent_local.polling.github_client.add_issue_label") as mock_add_label,
    ):
        mock_diff_stat.return_value = MagicMock(files_changed=[], lines_changed=0)

        result = process_issue(issue)

    assert result["decision"] == NO_ACTION_DECISION
    assert result["pr_number"] is None

    mock_record.assert_called_once()
    assert mock_record.call_args.kwargs["decision"] == NO_ACTION_DECISION
    assert mock_record.call_args.kwargs["pr_number"] is None
    assert mock_record.call_args.kwargs["issue_number"] == 41

    mock_comment.assert_called_once()
    assert "nenhuma" in mock_comment.call_args.args[1].lower() or "Nenhuma" in mock_comment.call_args.args[1]
    assert "A issue ja esta implementada" in mock_comment.call_args.args[1]

    # Achado real: fechar (nao so desatribuir) e o que impede a issue de
    # reaparecer em list_candidate_issues (filtro is:open) e recolidir com
    # a propria branch de trabalho numa selecao seguinte.
    mock_close.assert_called_once_with(41)
    mock_unassign.assert_not_called()
    mock_delete_branch.assert_called_once_with("/tmp/repo", "issue-41")

    mock_push.assert_not_called()
    mock_open_pr.assert_not_called()
    mock_apply_gate.assert_not_called()
    mock_add_label.assert_not_called()  # nao pode cair no caminho de retry/falha generica


def test_process_issue_no_action_needed_repassa_custo_e_duracao_do_sdk() -> None:
    """Issue #80: assim como no caminho com PR (gate.py), o destino 2
    (no-op) tambem precisa repassar `total_cost_usd`/`duration_ms` do
    `SDKInvocationResult` para `record_risk_decision` - sem este teste,
    remover essas duas linhas em `_handle_no_action_needed` nao quebraria
    nenhum teste existente."""
    issue = _issue(number=41)
    risk = _risk(diff_lines=0)
    sdk_result = _sdk_result(success=True, result_text="nada a fazer", duration_ms=12345)

    with (
        patch("agent_local.polling.get_settings", return_value=_full_settings()),
        patch("agent_local.polling.github_client.assign_self"),
        patch("agent_local.polling.git_ops.ensure_repo_cloned", return_value="/tmp/repo"),
        patch("agent_local.polling.git_ops.create_issue_branch", return_value="issue-41"),
        patch("agent_local.polling.invoke_sdk", return_value=sdk_result),
        patch("agent_local.polling.test_runner.get_diff_stat") as mock_diff_stat,
        patch("agent_local.polling.test_runner.detect_affected_services", return_value=[]),
        patch("agent_local.polling.calculate_risk_score", return_value=risk),
        patch("agent_local.polling.agent_ops_db.record_risk_decision") as mock_record,
        patch("agent_local.polling.github_client.comment_issue"),
        patch("agent_local.polling.github_client.close_issue"),
        patch("agent_local.polling.github_client.unassign_self"),
        patch("agent_local.polling.git_ops.delete_local_branch"),
    ):
        mock_diff_stat.return_value = MagicMock(files_changed=[], lines_changed=0)

        process_issue(issue)

    kwargs = mock_record.call_args.kwargs
    assert kwargs["total_cost_usd"] == 0.05
    assert kwargs["sdk_duration_ms"] == 12345


def test_process_issue_no_action_needed_falha_ao_limpar_branch_nao_propaga() -> None:
    """A limpeza da branch e melhor-esforco: a causa raiz (issue reaparecer
    como candidata) ja foi eliminada so pelo close_issue, entao uma falha
    ao apagar a branch orfa nao pode reverter o resultado nem ser tratada
    como falha de processamento (destino 3) - so logar e seguir."""
    issue = _issue(number=41)
    risk = _risk(diff_lines=0)
    sdk_result = _sdk_result(success=True, result_text="nada a fazer")

    with (
        patch("agent_local.polling.get_settings", return_value=_full_settings()),
        patch("agent_local.polling.github_client.assign_self"),
        patch("agent_local.polling.git_ops.ensure_repo_cloned", return_value="/tmp/repo"),
        patch("agent_local.polling.git_ops.create_issue_branch", return_value="issue-41"),
        patch("agent_local.polling.invoke_sdk", return_value=sdk_result),
        patch("agent_local.polling.test_runner.get_diff_stat") as mock_diff_stat,
        patch("agent_local.polling.test_runner.detect_affected_services", return_value=[]),
        patch("agent_local.polling.calculate_risk_score", return_value=risk),
        patch("agent_local.polling.agent_ops_db.record_risk_decision"),
        patch("agent_local.polling.github_client.comment_issue"),
        patch("agent_local.polling.github_client.close_issue") as mock_close,
        patch(
            "agent_local.polling.git_ops.delete_local_branch",
            side_effect=RuntimeError("branch ja foi apagada manualmente"),
        ),
        patch("agent_local.polling.notify_agent_error") as mock_notify,
    ):
        mock_diff_stat.return_value = MagicMock(files_changed=[], lines_changed=0)

        result = process_issue(issue)  # nao deve levantar

    assert result["decision"] == NO_ACTION_DECISION
    mock_close.assert_called_once_with(41)
    mock_notify.assert_not_called()


def test_process_issue_diff_lines_zero_sem_sdk_success_cai_em_falha_generica() -> None:
    """Se diff_lines==0 mas o SDK nao produziu result_text (`success=False`),
    nao ha confirmacao de que o SDK de fato concluiu - nao pode ser tratado
    como no-op legitimo, deve cair no destino 3 (falha generica) da #40:
    desatribui, comenta o motivo da falha e marca retry."""
    issue = _issue(number=41)
    risk = _risk(diff_lines=0)
    sdk_result = _sdk_result(success=False, result_text="")

    with (
        patch("agent_local.polling.get_settings", return_value=_full_settings()),
        patch("agent_local.polling.github_client.assign_self"),
        patch("agent_local.polling.git_ops.ensure_repo_cloned", return_value="/tmp/repo"),
        patch("agent_local.polling.git_ops.create_issue_branch", return_value="issue-41"),
        patch("agent_local.polling.invoke_sdk", return_value=sdk_result),
        patch("agent_local.polling.test_runner.get_diff_stat") as mock_diff_stat,
        patch("agent_local.polling.test_runner.detect_affected_services", return_value=[]),
        patch("agent_local.polling.calculate_risk_score", return_value=risk),
        patch("agent_local.polling.agent_ops_db.record_risk_decision") as mock_record,
        patch("agent_local.polling.github_client.comment_issue") as mock_comment,
        patch("agent_local.polling.github_client.unassign_self") as mock_unassign,
        patch("agent_local.polling.git_ops.push_branch") as mock_push,
        patch("agent_local.polling.open_pull_request") as mock_open_pr,
        patch("agent_local.polling.apply_gate") as mock_apply_gate,
        patch("agent_local.polling.github_client.add_issue_label") as mock_add_label,
    ):
        mock_diff_stat.return_value = MagicMock(files_changed=[], lines_changed=0)

        with pytest.raises(RuntimeError, match="sdk_result.success"):
            process_issue(issue)

    mock_record.assert_not_called()
    mock_push.assert_not_called()
    mock_open_pr.assert_not_called()
    mock_apply_gate.assert_not_called()

    mock_add_label.assert_called_once_with(41, "agent-retry-1")
    mock_comment.assert_called_once()
    assert "sdk_result.success" in mock_comment.call_args.args[1]
    mock_unassign.assert_called_once_with(41)


def test_process_issue_diff_lines_positivo_segue_fluxo_normal_sem_no_action() -> None:
    """Regressao: com diff_lines > 0, o fluxo normal (push/PR/gate) deve
    continuar intacto - o caminho de no-op nao pode interceptar o caso
    comum."""
    issue = _issue(number=41)
    risk = _risk(diff_lines=12)
    sdk_result = _sdk_result(success=True, result_text="Implementado.")

    with (
        patch("agent_local.polling.get_settings", return_value=_full_settings()),
        patch("agent_local.polling.github_client.assign_self"),
        patch("agent_local.polling.git_ops.ensure_repo_cloned", return_value="/tmp/repo"),
        patch("agent_local.polling.git_ops.create_issue_branch", return_value="issue-41"),
        patch("agent_local.polling.invoke_sdk", return_value=sdk_result),
        patch("agent_local.polling.test_runner.get_diff_stat") as mock_diff_stat,
        patch("agent_local.polling.test_runner.detect_affected_services", return_value=[]),
        patch("agent_local.polling.calculate_risk_score", return_value=risk),
        patch("agent_local.polling.agent_ops_db.record_risk_decision") as mock_record,
        patch("agent_local.polling.github_client.comment_issue") as mock_comment,
        patch("agent_local.polling.github_client.unassign_self") as mock_unassign,
        patch("agent_local.polling.git_ops.push_branch") as mock_push,
        patch("agent_local.polling.open_pull_request", return_value=(7, "https://github.com/x/y/pull/7")) as mock_open_pr,
        patch("agent_local.polling.apply_gate", return_value="humano") as mock_apply_gate,
    ):
        mock_diff_stat.return_value = MagicMock(files_changed=["a.py"], lines_changed=12)

        result = process_issue(issue)

    assert result["decision"] == "humano"
    assert result["pr_number"] == 7
    mock_push.assert_called_once()
    mock_open_pr.assert_called_once()
    mock_apply_gate.assert_called_once()
    mock_record.assert_not_called()  # a auditoria no fluxo normal e responsabilidade do apply_gate, nao do polling
    mock_comment.assert_not_called()
    mock_unassign.assert_not_called()  # issue continua atribuida no fluxo normal (nao ha destino 2/3 aqui)


def test_current_retry_count_le_label_de_retry() -> None:
    assert _current_retry_count(["bug", "agent-retry-2"]) == 2


def test_current_retry_count_sem_label_e_zero() -> None:
    assert _current_retry_count(["bug", "chaos-test"]) == 0


def test_process_issue_falha_generica_desatribui_comenta_e_marca_retry() -> None:
    """Destino 3 (specs/tech/error-handling.md): uma excecao nao tratada
    apos assign_self precisa desatribuir a issue, comentar o motivo e
    devolve-la a fila - nunca deixa-la presa, atribuida e silenciosa."""
    issue = _issue(number=42, labels=["bug"])
    with (
        patch("agent_local.polling.get_settings", return_value=_settings(max_consecutive_failures=3)),
        patch("agent_local.polling.github_client.assign_self") as mock_assign,
        patch("agent_local.polling.git_ops.ensure_repo_cloned", side_effect=RuntimeError("SDK indisponível")),
        patch("agent_local.polling.github_client.add_issue_label") as mock_add_label,
        patch("agent_local.polling.github_client.remove_issue_label") as mock_remove_label,
        patch("agent_local.polling.github_client.comment_issue") as mock_comment,
        patch("agent_local.polling.github_client.unassign_self") as mock_unassign,
    ):
        with pytest.raises(RuntimeError):
            process_issue(issue)

    mock_assign.assert_called_once_with(42)
    mock_add_label.assert_called_once_with(42, "agent-retry-1")
    mock_remove_label.assert_not_called()
    mock_comment.assert_called_once()
    assert "SDK indisponível" in mock_comment.call_args.args[1]
    mock_unassign.assert_called_once_with(42)


def test_process_issue_escala_ao_atingir_teto_de_falhas_consecutivas() -> None:
    """Terceira falha consecutiva (teto=3) nao deve devolver a issue a
    fila - deve escalar via label `agent-stuck` e permanecer atribuida
    (specs/tech/error-handling.md, "evitando um loop de retry sem teto")."""
    issue = _issue(number=7, labels=["bug", "agent-retry-2"])
    with (
        patch("agent_local.polling.get_settings", return_value=_settings(max_consecutive_failures=3)),
        patch("agent_local.polling.github_client.assign_self"),
        patch("agent_local.polling.git_ops.ensure_repo_cloned", side_effect=RuntimeError("falha persistente")),
        patch("agent_local.polling.github_client.add_issue_label") as mock_add_label,
        patch("agent_local.polling.github_client.remove_issue_label") as mock_remove_label,
        patch("agent_local.polling.github_client.comment_issue") as mock_comment,
        patch("agent_local.polling.github_client.unassign_self") as mock_unassign,
    ):
        with pytest.raises(RuntimeError):
            process_issue(issue)

    mock_remove_label.assert_called_once_with(7, "agent-retry-2")
    mock_add_label.assert_called_once_with(7, AGENT_STUCK_LABEL)
    mock_comment.assert_called_once()
    mock_unassign.assert_not_called()  # fica atribuida de proposito - e o que a mantem fora da fila


def test_process_issue_propaga_excecao_original_mesmo_se_limpeza_falhar(caplog) -> None:
    """Pior caso: ate a limpeza pos-falha (unassign/comment) falha (ex. `gh`
    indisponivel). A excecao original nao pode ser mascarada - so logada
    como critica para investigacao manual."""
    issue = _issue(number=9, labels=[])
    with (
        caplog.at_level(logging.CRITICAL, logger="agent_local.polling"),
        patch("agent_local.polling.get_settings", return_value=_settings(max_consecutive_failures=3)),
        patch("agent_local.polling.github_client.assign_self"),
        patch("agent_local.polling.git_ops.ensure_repo_cloned", side_effect=RuntimeError("falha original")),
        patch("agent_local.polling.github_client.add_issue_label", side_effect=RuntimeError("gh indisponível")),
    ):
        with pytest.raises(RuntimeError, match="falha original"):
            process_issue(issue)

    messages = [record.message for record in caplog.records]
    assert any("presa" in m for m in messages)
