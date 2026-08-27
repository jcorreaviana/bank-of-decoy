"""Wrapper fino sobre `gh` CLI - todas as interacoes com issues/PRs do
agente local passam por aqui (specs/business/14-agente-local.md). Nenhuma
chamada de rede direta a API do GitHub - reusa a mesma autenticacao do
`gh` ja configurada no ambiente, mesmo padrao usado no resto do projeto
(agent-preditivo/registration_agent.py)."""

import json
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    body: str
    labels: list[str]
    assignees: list[str]
    url: str


def _run(args: list[str]) -> str:
    # encoding="utf-8" explicito: sem isso, `text=True` decodifica com o
    # encoding padrao do locale (cp1252 no Windows), corrompendo qualquer
    # acento no titulo/corpo da issue (achado real ao validar a issue #16 -
    # "crítico" virava lixo, o parser de risk_score.py silenciosamente caia
    # no default conservador em vez de ler o valor real).
    result = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", check=True)
    return result.stdout


def list_candidate_issues() -> list[Issue]:
    """Issues abertas com label `business-story` ou `bug`, sem assignee."""
    raw = _run(
        [
            "issue",
            "list",
            "--search",
            "is:open no:assignee label:business-story,bug",
            "--json",
            "number,title,body,labels,assignees,url",
            "--limit",
            "50",
        ]
    )
    data = json.loads(raw)
    return [
        Issue(
            number=item["number"],
            title=item["title"],
            body=item["body"] or "",
            labels=[label["name"] for label in item["labels"]],
            assignees=[a["login"] for a in item["assignees"]],
            url=item["url"],
        )
        for item in data
    ]


def view_issue(number: int) -> Issue:
    raw = _run(["issue", "view", str(number), "--json", "number,title,body,labels,assignees,url"])
    item = json.loads(raw)
    return Issue(
        number=item["number"],
        title=item["title"],
        body=item["body"] or "",
        labels=[label["name"] for label in item["labels"]],
        assignees=[a["login"] for a in item["assignees"]],
        url=item["url"],
    )


def is_issue_open(number: int) -> bool:
    raw = _run(["issue", "view", str(number), "--json", "state"])
    return json.loads(raw)["state"] == "OPEN"


def assign_self(number: int) -> None:
    _run(["issue", "edit", str(number), "--add-assignee", "@me"])


def comment_issue(number: int, body: str) -> None:
    _run(["issue", "comment", str(number), "--body", body])


def create_pr(title: str, body: str, base: str, head: str, cwd: str) -> tuple[int, str]:
    result = subprocess.run(
        ["gh", "pr", "create", "--title", title, "--body", body, "--base", base, "--head", head],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        cwd=cwd,
    )
    url = result.stdout.strip().splitlines()[-1]
    pr_number = int(url.rstrip("/").rsplit("/", 1)[-1])
    return pr_number, url


def add_pr_label(pr_number: int, label: str) -> None:
    _run(["pr", "edit", str(pr_number), "--add-label", label])


def comment_pr(pr_number: int, body: str) -> None:
    _run(["pr", "comment", str(pr_number), "--body", body])


def merge_pr(pr_number: int) -> None:
    """Squash merge + apaga a branch remota - decisao de implementacao para
    manter o historico de `main` limpo (um commit por issue), documentada
    aqui por nao haver convencao explicita no resto do repositorio para
    merges automatizados."""
    _run(["pr", "merge", str(pr_number), "--squash", "--delete-branch"])
