"""Loop de polling do agente local - orquestra o fluxo completo (passos
1-8 de specs/business/14-agente-local.md). `--once` roda um unico ciclo,
para validacao/CI."""

import argparse
import logging
import re
import time
import traceback
from pathlib import Path

from notifications import notify_agent_error

from agent_local import git_ops, github_client, test_runner
from agent_local.config import get_settings
from agent_local.dependency_check import has_open_dependency
from agent_local.gate import apply_gate, open_pull_request
from agent_local.github_client import Issue
from agent_local.logging_config import configure_logging, new_trace_id
from agent_local.risk_score import calculate_risk_score
from agent_local.sdk_invocation import build_task_prompt, invoke_sdk

logger = logging.getLogger(__name__)

_SPEC_REF_PATTERN = re.compile(r"`(specs/business/[\w.\-]+\.md)`")

AGENT_STUCK_LABEL = "agent-stuck"
"""Aplicado no lugar de desatribuir a issue quando o numero de falhas
consecutivas atinge o teto (specs/tech/error-handling.md) - deliberadamente
mantem a issue atribuida, porque `list_candidate_issues` exige
`no:assignee`: ficar atribuida e o proprio mecanismo que impede o retorno a
fila, sem precisar alterar a query de busca nem duplicar essa regra em dois
lugares."""

_RETRY_LABEL_PATTERN = re.compile(r"^agent-retry-(\d+)$")

CHAOS_ORIGIN_LABEL = "chaos-test"
"""Issue de bug criada pelo agent-preditivo enquanto CHAOS_ENABLED estava
ativo no servico afetado (specs/business/21-filtro-caos-pipeline-agentes.md)
- e falha simulada, nao bug de codigo. O agente local nunca deve tentar
"corrigir" isso: nao ha nada errado no codigo para reverter, e o unico
efeito de tentar seria o agente propor mexer no proprio middleware de caos
(shared/chaos) e, pior, fazer merge automatico dessa reversao indevida se
o score de risco vier baixo."""


def pick_candidate_issue() -> Issue | None:
    candidates = github_client.list_candidate_issues()
    logger.info(
        "Issues candidatas consultadas no board.",
        extra={
            "context": {
                "total_candidatas": len(candidates),
                "issue_numbers": [issue.number for issue in candidates],
            }
        },
    )
    for issue in candidates:
        if CHAOS_ORIGIN_LABEL in issue.labels:
            logger.info(
                "Issue pulada - origem caos.",
                extra={"context": {"issue_number": issue.number, "motivo": f"label {CHAOS_ORIGIN_LABEL}"}},
            )
            continue
        if has_open_dependency(issue.body):
            logger.info(
                "Issue pulada - dependência aberta.",
                extra={"context": {"issue_number": issue.number, "motivo": "dependência ainda aberta"}},
            )
            continue
        logger.info("Issue candidata selecionada.", extra={"context": {"issue_number": issue.number}})
        return issue
    logger.info("Nenhuma issue candidata disponível neste ciclo.")
    return None


def _read_spec_text(repo_dir: str, issue_body: str) -> str | None:
    match = _SPEC_REF_PATTERN.search(issue_body)
    if not match:
        return None
    spec_path = Path(repo_dir) / match.group(1)
    if not spec_path.exists():
        return None
    return spec_path.read_text(encoding="utf-8")


def _current_retry_count(labels: list[str]) -> int:
    for label in labels:
        match = _RETRY_LABEL_PATTERN.match(label)
        if match:
            return int(match.group(1))
    return 0


def _handle_process_issue_failure(issue: Issue, exc: Exception, max_consecutive_failures: int) -> None:
    """Destino 3 do ciclo de vida pos-`assign_self`
    (specs/tech/error-handling.md): toda excecao nao prevista nos outros
    destinos precisa terminar em algo visivel na issue - nunca deixa-la
    atribuida, sem comentario e sem retornar a fila (a menos que tenha
    escalado por falhas repetidas, ver `AGENT_STUCK_LABEL`).

    Contagem de falhas consecutivas via label incremental
    (`agent-retry-N`) em vez de tabela no Postgres `agent_ops`: este modulo
    ja fala com o GitHub exclusivamente via `gh` (github_client.py), sem
    nenhuma escrita direta a estado de issue fora dali - uma tabela nova
    exigiria migration em outro servico (agent-ops-service) so para
    replicar um contador que o proprio GitHub ja hospeda nativamente, e sem
    o beneficio de ficar visivel na UI da issue para quem for investigar.
    Mesmo padrao ja usado pelo gate (`needs-human-review`, gate.py)."""
    current_count = _current_retry_count(issue.labels)
    new_count = current_count + 1

    if current_count > 0:
        github_client.remove_issue_label(issue.number, f"agent-retry-{current_count}")

    if new_count >= max_consecutive_failures:
        github_client.add_issue_label(issue.number, AGENT_STUCK_LABEL)
        github_client.comment_issue(
            issue.number,
            f"Falha ao processar automaticamente ({new_count}x consecutivas): {exc}\n\n"
            f"Escalado para revisão humana (label `{AGENT_STUCK_LABEL}`) - a issue "
            "permanece atribuída de propósito, para não voltar à fila de candidatas "
            "sem intervenção manual.",
        )
        logger.error(
            "Issue escalada apos falhas consecutivas.",
            extra={
                "context": {
                    "issue_number": issue.number,
                    "falhas_consecutivas": new_count,
                    "motivo": str(exc),
                }
            },
        )
        return

    github_client.add_issue_label(issue.number, f"agent-retry-{new_count}")
    github_client.comment_issue(
        issue.number,
        f"Falha ao processar automaticamente (tentativa {new_count}/{max_consecutive_failures}): {exc}\n\n"
        "Issue desatribuída - volta a ficar elegível para uma nova tentativa.",
    )
    github_client.unassign_self(issue.number)
    logger.warning(
        "Issue desatribuída apos falha - devolvida a fila de candidatas.",
        extra={
            "context": {
                "issue_number": issue.number,
                "falhas_consecutivas": new_count,
                "motivo": str(exc),
            }
        },
    )


def process_issue(issue: Issue) -> dict:
    settings = get_settings()

    logger.info(
        "Issue auto-atribuída para processamento.",
        extra={"context": {"issue_number": issue.number, "title": issue.title}},
    )
    github_client.assign_self(issue.number)

    try:
        repo_dir = git_ops.ensure_repo_cloned(settings.repo_url, settings.repo_clone_dir)
        branch = git_ops.create_issue_branch(repo_dir, issue.number)

        spec_text = _read_spec_text(repo_dir, issue.body)
        prompt = build_task_prompt(issue.number, issue.title, issue.body, spec_text)
        sdk_result = invoke_sdk(
            prompt,
            cwd=repo_dir,
            model=settings.model,
            max_turns=settings.max_turns,
            timeout_seconds=settings.sdk_timeout_seconds,
        )

        diff_stat = test_runner.get_diff_stat(repo_dir)
        affected_services = test_runner.detect_affected_services(diff_stat.files_changed)

        test_database_url = (
            f"postgresql://bank:bank@{settings.test_database_host}:{settings.test_database_port}"
        )
        coverage_fractions = []
        for service in affected_services:
            result = test_runner.run_tests_for_service(service, repo_dir, f"{test_database_url}/{service.replace('-service', '').replace('-', '_')}")
            coverage_fractions.append(result.coverage_fraction)
        coverage_fraction = min(coverage_fractions) if coverage_fractions else 0.0

        risk = calculate_risk_score(issue.body, coverage_fraction, diff_stat.lines_changed)
        logger.info(
            "Score de risco calculado.",
            extra={
                "context": {
                    "issue_number": issue.number,
                    "score": risk.score,
                    "threshold": risk.threshold,
                    "decision": risk.decision,
                    "category": risk.risk_fields.category,
                    "criticality": risk.risk_fields.criticality,
                    "coverage_fraction": risk.coverage_fraction,
                    "diff_lines": risk.diff_lines,
                }
            },
        )

        git_ops.push_branch(repo_dir, branch)
        pr_number, pr_url = open_pull_request(issue.number, branch, repo_dir, title=f"{issue.title} (#{issue.number})")
        decision = apply_gate(issue.number, pr_number, pr_url, risk)

        return {
            "issue_number": issue.number,
            "pr_number": pr_number,
            "score": risk.score,
            "decision": decision,
            "sdk_success": sdk_result.success,
            "sdk_cost_usd": sdk_result.total_cost_usd,
        }
    except Exception as exc:
        try:
            _handle_process_issue_failure(issue, exc, settings.max_consecutive_failures)
        except Exception:
            # Falha na propria limpeza (ex. `gh` indisponivel) e o pior caso
            # possivel para o contrato de specs/tech/error-handling.md - a
            # issue pode ficar mesmo presa (atribuida, sem comentario). Nao
            # deixar essa segunda excecao mascarar a original nem escapar
            # silenciosa - so logar como critico para investigacao manual.
            logger.critical(
                "Falha ao aplicar destino 3 (limpeza pos-falha) - issue pode ficar presa.",
                exc_info=True,
                extra={"context": {"issue_number": issue.number}},
            )
        raise


def run_cycle() -> dict | None:
    """Erro nao tratado ao processar uma issue (SDK indisponivel, falha de
    rede, exceção inesperada) e notificado e logado, mas NAO derruba o
    processo - mesmo racional do agent-preditivo (specs/business/20-notificacoes-discord-agentes.md,
    evento 4): a notificacao e o alerta para intervencao humana, um daemon
    de polling deve sobreviver a falhas transitorias e tentar de novo no
    proximo ciclo."""
    new_trace_id()  # um trace_id por ciclo - todos os logs deste ciclo ficam correlacionados
    logger.info("Ciclo do agent-local iniciado.")
    issue = pick_candidate_issue()
    if issue is None:
        logger.info("Ciclo do agent-local concluído sem candidata - nenhuma ação tomada.")
        return None
    try:
        result = process_issue(issue)
        logger.info(
            "Ciclo do agent-local concluído.",
            extra={"context": {"issue_number": issue.number, "decision": result.get("decision")}},
        )
        return result
    except Exception as exc:
        logger.error(
            "Erro nao tratado processando issue no agent-local.",
            extra={"context": {"issue_number": issue.number, "stack_trace": traceback.format_exc()}},
        )
        notify_agent_error(
            "agent-local",
            str(exc),
            context={"issue": f"#{issue.number}", "traceback": traceback.format_exc()[-500:]},
        )
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente local - polling de issues")
    parser.add_argument("--once", action="store_true", help="roda um único ciclo e encerra (para validação/CI)")
    args = parser.parse_args()

    settings = get_settings()
    configure_logging("agent-local", settings.log_level)
    if args.once:
        result = run_cycle()
        print(result)
        return

    while True:
        run_cycle()
        time.sleep(settings.interval_seconds)


if __name__ == "__main__":
    main()
