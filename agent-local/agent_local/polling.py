"""Loop de polling do agente local - orquestra o fluxo completo (passos
1-8 de specs/business/14-agente-local.md). `--once` roda um unico ciclo,
para validacao/CI."""

import argparse
import re
import time
from pathlib import Path

from agent_local import git_ops, github_client, test_runner
from agent_local.config import get_settings
from agent_local.dependency_check import has_open_dependency
from agent_local.gate import apply_gate, open_pull_request
from agent_local.github_client import Issue
from agent_local.risk_score import calculate_risk_score
from agent_local.sdk_invocation import build_task_prompt, invoke_sdk

_SPEC_REF_PATTERN = re.compile(r"`(specs/business/[\w.\-]+\.md)`")


def pick_candidate_issue() -> Issue | None:
    for issue in github_client.list_candidate_issues():
        if has_open_dependency(issue.body):
            continue
        return issue
    return None


def _read_spec_text(repo_dir: str, issue_body: str) -> str | None:
    match = _SPEC_REF_PATTERN.search(issue_body)
    if not match:
        return None
    spec_path = Path(repo_dir) / match.group(1)
    if not spec_path.exists():
        return None
    return spec_path.read_text(encoding="utf-8")


def process_issue(issue: Issue) -> dict:
    settings = get_settings()

    github_client.assign_self(issue.number)

    repo_dir = git_ops.ensure_repo_cloned(settings.repo_url, settings.repo_clone_dir)
    branch = git_ops.create_issue_branch(repo_dir, issue.number)

    spec_text = _read_spec_text(repo_dir, issue.body)
    prompt = build_task_prompt(issue.number, issue.title, issue.body, spec_text)
    sdk_result = invoke_sdk(prompt, cwd=repo_dir, model=settings.model, max_turns=settings.max_turns)

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

    git_ops.push_branch(repo_dir, branch)
    pr_number = open_pull_request(issue.number, branch, repo_dir, title=f"{issue.title} (#{issue.number})")
    decision = apply_gate(issue.number, pr_number, risk)

    return {
        "issue_number": issue.number,
        "pr_number": pr_number,
        "score": risk.score,
        "decision": decision,
        "sdk_success": sdk_result.success,
        "sdk_cost_usd": sdk_result.total_cost_usd,
    }


def run_cycle() -> dict | None:
    issue = pick_candidate_issue()
    if issue is None:
        return None
    return process_issue(issue)


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente local - polling de issues")
    parser.add_argument("--once", action="store_true", help="roda um único ciclo e encerra (para validação/CI)")
    args = parser.parse_args()

    settings = get_settings()
    if args.once:
        result = run_cycle()
        print(result)
        return

    while True:
        run_cycle()
        time.sleep(settings.interval_seconds)


if __name__ == "__main__":
    main()
