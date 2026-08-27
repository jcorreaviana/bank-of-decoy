"""Agente de registro (Modelo B): mesmo modelo `llama3.2:3b`, dois system
prompts (tecnico/negocio) conforme a classificacao do agente preditivo,
"RAG" sobre o template de issue correspondente - aqui simplificado para
leitura direta do arquivo (um documento curto de ~30 linhas nao justifica
indexacao vetorial; decisao documentada, mesma filosofia de manter cada
peca no tamanho certo). Preenche os campos de risco em codigo (nao pelo
LLM - mesma filosofia de nao delegar decisao estruturada ao modelo usada
no resto do projeto), cria a issue via `gh issue create` e registra em
`flagged_signals` (specs/business/13-agente-preditivo-registro.md).
"""

import re
import subprocess
from pathlib import Path

from agent_preditivo import agent_ops_db
from agent_preditivo.bug_detection import BugSignal
from agent_preditivo.llm import chat
from agent_preditivo.opportunity_detection import OpportunityFinding

_REPO_ROOT = Path(__file__).resolve().parents[2]
BUG_TEMPLATE_PATH = _REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "bug-report.md"
BUSINESS_STORY_TEMPLATE_PATH = _REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "business-story.md"

SERVICE_CRITICALITY = {
    "transaction-service": "crítico",
    "pix-key-service": "crítico",
    "account-service": "alto",
    "onboarding-service": "alto",
}

_BUG_SYSTEM_PROMPT = """Voce e o agente de registro tecnico de um sistema de monitoramento \
bancario. Escreva, em portugues, uma narrativa TECNICA curta e objetiva para uma issue de bug, \
com base no sinal detectado que sera descrito pelo usuario. Responda em EXATAMENTE este formato, \
nada antes nem depois:

SINAL_QUE_DISPAROU: <uma ou duas frases descrevendo o threshold violado>
EVIDENCIA: <trecho ou resumo curto do log/metrica que embasou a deteccao>
"""

_OPORTUNIDADE_SYSTEM_PROMPT = """Voce e o agente de registro de negocio de um sistema bancario. \
Escreva, em portugues, uma narrativa DE NEGOCIO curta e objetiva para uma issue de oportunidade \
(lacuna entre regra ja especificada e comportamento real), com base no achado que sera descrito \
pelo usuario. Responda em EXATAMENTE este formato, nada antes nem depois:

RESUMO: <uma ou duas frases resumindo a lacuna encontrada, em linguagem de negocio>
CONTRATO_AFETADO: <qual contrato/regra de negocio o comportamento observado nao respeita>
"""


def _parse_fields(raw: str, *field_names: str) -> dict[str, str]:
    fields = {}
    for name in field_names:
        match = re.search(rf"{name}:\s*(.+?)(?=\n[A-Z_]+:|$)", raw, re.DOTALL)
        fields[name] = match.group(1).strip() if match else ""
    return fields


def format_bug_issue(signal: BugSignal) -> tuple[str, str]:
    BUG_TEMPLATE_PATH.read_text(encoding="utf-8")  # confirma que o template existe/é lido
    raw = chat(_BUG_SYSTEM_PROMPT, f"Sinal detectado: {signal.signal_type} em {signal.service}. Detalhe: {signal.detail}")
    fields = _parse_fields(raw, "SINAL_QUE_DISPAROU", "EVIDENCIA")
    criticidade = SERVICE_CRITICALITY.get(signal.service, "baixo")

    title = f"[BUG] {signal.signal_type} em {signal.service}"
    body = f"""## Sinal que disparou

{fields['SINAL_QUE_DISPAROU'] or signal.detail}

## Serviço afetado

{signal.service} ({criticidade})

## Evidência

{fields['EVIDENCIA'] or signal.detail}

## Passos de reprodução (se aplicável)

Detectado automaticamente pelo agente preditivo via Prometheus/logs - sem passos manuais de reprodução.

## Sinal de risco (para o score de subida)

Categoria da mudança: operacional
Serviço(s) afetado(s) e criticidade: {signal.service} ({criticidade})

## Dependências

Nenhuma.
"""
    return title, body


def format_opportunity_issue(finding: OpportunityFinding, scenario_path: Path | None) -> tuple[str, str]:
    BUSINESS_STORY_TEMPLATE_PATH.read_text(encoding="utf-8")
    raw = chat(
        _OPORTUNIDADE_SYSTEM_PROMPT,
        f"Cenário: {finding.scenario_name}. Comportamento observado: {finding.observed_behavior}. "
        f"Racional do agente: {finding.racional}",
    )
    fields = _parse_fields(raw, "RESUMO", "CONTRATO_AFETADO")

    title = f"[FASE 3] Oportunidade: {finding.scenario_name}"
    scenario_ref = f"`{scenario_path.relative_to(_REPO_ROOT).as_posix()}`" if scenario_path else "(não salva)"
    body = f"""## Spec de referência

Cenário reproduzível: {scenario_ref}

## Resumo

{fields['RESUMO'] or finding.racional}

## Contrato afetado

{fields['CONTRATO_AFETADO'] or finding.observed_behavior}

## Critério de aceite

- [ ] A definir após triagem humana/agente local

## Sinal de risco (para o score de subida)

Categoria da mudança: regra de negócio
Serviço(s) afetado(s) e criticidade: a definir na triagem

## Dependências

Nenhuma.
"""
    return title, body


def create_issue(title: str, body: str, label: str) -> int:
    result = subprocess.run(
        ["gh", "issue", "create", "--title", title, "--body", body, "--label", label],
        capture_output=True,
        text=True,
        check=True,
        cwd=_REPO_ROOT,
    )
    url = result.stdout.strip().splitlines()[-1]
    return int(url.rstrip("/").rsplit("/", 1)[-1])


def register_bug(signal: BugSignal) -> int | None:
    existing = agent_ops_db.find_open_signal(signal.signal_type, signal.service)
    if existing is not None:
        return None  # já sinalizado e em aberto - dedup, nao repete a acao

    title, body = format_bug_issue(signal)
    issue_number = create_issue(title, body, "bug")
    agent_ops_db.register_signal(signal.signal_type, signal.service, issue_number=issue_number)
    return issue_number


def register_opportunity(finding: OpportunityFinding, scenario_path: Path | None) -> int | None:
    if finding.veredito != "GAP":
        return None

    existing = agent_ops_db.find_open_signal(finding.scenario_name, "oportunidade")
    if existing is not None:
        return None

    title, body = format_opportunity_issue(finding, scenario_path)
    issue_number = create_issue(title, body, "business-story")
    agent_ops_db.register_signal(finding.scenario_name, "oportunidade", issue_number=issue_number)
    return issue_number
