"""Gate de aprovacao (specs/business/14-agente-local.md, passo 8): sempre
abre PR, nunca push direto para main. Score abaixo do threshold do tier ->
aprova e faz merge sozinho. Score acima -> label `needs-human-review`,
comentario explicando o score, sem merge.

Roda inteiramente em codigo deterministico (nunca dentro da invocacao do
SDK - ver sdk_invocation.py)."""

import logging

from notifications import notify_auto_merge, notify_pr_needs_review

from agent_local import agent_ops_db, github_client
from agent_local.risk_score import RiskScoreResult

logger = logging.getLogger(__name__)


def open_pull_request(issue_number: int, branch: str, repo_dir: str, title: str) -> tuple[int, str]:
    body = f"Implementa a issue #{issue_number}, via agent-local (Claude Agent SDK).\n\nCloses #{issue_number}"
    return github_client.create_pr(title=title, body=body, base="main", head=branch, cwd=repo_dir)


def apply_gate(issue_number: int, pr_number: int, pr_url: str, risk: RiskScoreResult) -> str:
    """Retorna a decisao aplicada ("autonomo" | "humano") apos executar as
    acoes correspondentes (merge ou label+comentario)."""
    racional = (
        f"Score de risco: {risk.score:.2f} (threshold do tier "
        f"'{risk.risk_fields.criticality}': {risk.threshold}). "
        f"Categoria da mudança: {risk.risk_fields.category.replace('_', ' ')}"
        f"{' (não reconhecida na issue, default conservador aplicado)' if not risk.risk_fields.category_parsed else ''}. "
        f"Criticidade do serviço: {risk.risk_fields.criticality}"
        f"{' (não reconhecida na issue, default conservador aplicado)' if not risk.risk_fields.criticality_parsed else ''}. "
        f"Cobertura de teste: {risk.coverage_fraction:.0%}. Diff: {risk.diff_lines} linhas."
    )

    if risk.decision == "autonomo":
        github_client.comment_pr(pr_number, f"Score abaixo do threshold - merge automático.\n\n{racional}")
        github_client.merge_pr(pr_number)
        notify_auto_merge(issue_number, pr_number, risk.score, pr_url)
        logger.info(
            "Merge automático aplicado.",
            extra={
                "context": {
                    "issue_number": issue_number,
                    "pr_number": pr_number,
                    "score": risk.score,
                    "threshold": risk.threshold,
                    "racional": racional,
                }
            },
        )
    else:
        github_client.add_pr_label(pr_number, "needs-human-review")
        github_client.comment_pr(
            pr_number, f"Score acima do threshold - aguardando revisão humana.\n\n{racional}"
        )
        notify_pr_needs_review(pr_number, pr_url, risk.score, risk.threshold)
        logger.info(
            "PR aguardando revisão humana.",
            extra={
                "context": {
                    "issue_number": issue_number,
                    "pr_number": pr_number,
                    "score": risk.score,
                    "threshold": risk.threshold,
                    "racional": racional,
                }
            },
        )

    agent_ops_db.record_risk_decision(
        issue_number=issue_number,
        risk_score=risk.score,
        threshold_used=risk.threshold,
        service_criticality=risk.risk_fields.criticality,
        decision=risk.decision,
        pr_number=pr_number,
    )

    return risk.decision
