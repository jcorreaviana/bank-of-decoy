from unittest.mock import patch

from agent_local.gate import apply_gate
from agent_local.risk_score import RiskFields, RiskScoreResult


def _risk(decision: str, score: float = 10.0, threshold: float = 20.0) -> RiskScoreResult:
    return RiskScoreResult(
        score=score,
        threshold=threshold,
        decision=decision,
        risk_fields=RiskFields(
            category="operacional", criticality="critico", category_parsed=True, criticality_parsed=True
        ),
        coverage_fraction=0.9,
        diff_lines=20,
    )


def test_apply_gate_score_baixo_faz_merge_automatico() -> None:
    with (
        patch("agent_local.gate.github_client.comment_pr") as mock_comment,
        patch("agent_local.gate.github_client.merge_pr") as mock_merge,
        patch("agent_local.gate.github_client.add_pr_label") as mock_label,
        patch("agent_local.gate.agent_ops_db.record_risk_decision") as mock_record,
        patch("agent_local.gate.notify_auto_merge") as mock_notify_merge,
        patch("agent_local.gate.notify_pr_needs_review") as mock_notify_review,
    ):
        decision = apply_gate(issue_number=42, pr_number=7, pr_url="https://github.com/x/y/pull/7", risk=_risk("autonomo"))

    assert decision == "autonomo"
    mock_merge.assert_called_once_with(7)
    mock_label.assert_not_called()
    mock_comment.assert_called_once()
    mock_record.assert_called_once()
    assert mock_record.call_args.kwargs["decision"] == "autonomo"
    mock_notify_merge.assert_called_once_with(42, 7, 10.0, "https://github.com/x/y/pull/7")
    mock_notify_review.assert_not_called()


def test_apply_gate_score_alto_abre_para_revisao_sem_merge() -> None:
    with (
        patch("agent_local.gate.github_client.comment_pr") as mock_comment,
        patch("agent_local.gate.github_client.merge_pr") as mock_merge,
        patch("agent_local.gate.github_client.add_pr_label") as mock_label,
        patch("agent_local.gate.agent_ops_db.record_risk_decision") as mock_record,
        patch("agent_local.gate.notify_auto_merge") as mock_notify_merge,
        patch("agent_local.gate.notify_pr_needs_review") as mock_notify_review,
    ):
        decision = apply_gate(
            issue_number=42, pr_number=7, pr_url="https://github.com/x/y/pull/7", risk=_risk("humano", score=90.0)
        )

    assert decision == "humano"
    mock_merge.assert_not_called()
    mock_label.assert_called_once_with(7, "needs-human-review")
    mock_comment.assert_called_once()
    assert mock_record.call_args.kwargs["decision"] == "humano"
    mock_notify_review.assert_called_once_with(7, "https://github.com/x/y/pull/7", 90.0, 20.0)
    mock_notify_merge.assert_not_called()


def test_apply_gate_registra_auditoria_com_campos_corretos() -> None:
    with (
        patch("agent_local.gate.github_client.comment_pr"),
        patch("agent_local.gate.github_client.merge_pr"),
        patch("agent_local.gate.agent_ops_db.record_risk_decision") as mock_record,
        patch("agent_local.gate.notify_auto_merge"),
        patch("agent_local.gate.notify_pr_needs_review"),
    ):
        apply_gate(
            issue_number=42,
            pr_number=7,
            pr_url="https://github.com/x/y/pull/7",
            risk=_risk("autonomo", score=15.5, threshold=20.0),
        )

    kwargs = mock_record.call_args.kwargs
    assert kwargs["issue_number"] == 42
    assert kwargs["pr_number"] == 7
    assert kwargs["risk_score"] == 15.5
    assert kwargs["threshold_used"] == 20.0
    assert kwargs["service_criticality"] == "critico"
