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

import logging
import re
import subprocess
from pathlib import Path

from notifications import notify_issue_created

from agent_preditivo import agent_ops_db
from agent_preditivo.bug_detection import BugSignal
from agent_preditivo.llm import chat
from agent_preditivo.opportunity_detection import OpportunityFinding

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
BUG_TEMPLATE_PATH = _REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "bug-report.md"
BUSINESS_STORY_TEMPLATE_PATH = _REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "business-story.md"

CHAOS_ORIGIN_LABEL = "chaos-test"
"""Mesma label que agent-local/agent_local/polling.py:CHAOS_ORIGIN_LABEL
usa para pular a issue - as duas pontas precisam concordar no nome
(specs/business/21-filtro-caos-pipeline-agentes.md)."""

SERVICE_CRITICALITY = {
    "transaction-service": "crítico",
    "pix-key-service": "crítico",
    "account-service": "alto",
    "onboarding-service": "alto",
}

_TECH_SPECS = [
    "stack.md",
    "logging.md",
    "database.md",
    "error-handling.md",
    "api-conventions.md",
    "testing.md",
    "observability.md",
    "messaging.md",
    "security.md",
    "infrastructure.md",
]

_GENERIC_CRITERIO_ITEM = "A definir após triagem humana/agente local"

_BUSINESS_SPECS_DIR = _REPO_ROOT / "specs" / "business"

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
SPECS_TECNICAS: <lista separada por virgula, somente com nomes exatos dentre: stack.md, logging.md, \
database.md, error-handling.md, api-conventions.md, testing.md, observability.md, messaging.md, \
security.md, infrastructure.md - inclua so as realmente relevantes para esse achado especifico, \
ou "nenhuma" se nenhuma se aplicar>
CRITERIO_ACEITE: <entre 2 e 4 itens verificaveis reais derivados do achado, um por linha, cada \
linha comecando com "- ", sem numeracao>
"""


def _parse_fields(raw: str, *field_names: str) -> dict[str, str]:
    fields = {}
    for name in field_names:
        match = re.search(rf"{name}:\s*(.+?)(?=\n[A-Z_]+:|$)", raw, re.DOTALL)
        fields[name] = match.group(1).strip() if match else ""
    return fields


def _parse_specs_tecnicas(raw_field: str) -> list[str]:
    if not raw_field:
        return []
    candidatos = {item.strip().lower() for item in raw_field.split(",")}
    return [spec for spec in _TECH_SPECS if spec.lower() in candidatos]


def _parse_criterio_items(raw_field: str) -> list[str]:
    items = []
    for line in raw_field.splitlines():
        line = line.strip()
        previous = None
        while line != previous:
            # o LLM as vezes empilha marcadores (ex. "- - item", "- [ ] item") -
            # remove uma camada por iteracao ate estabilizar, nao so uma vez
            # (achado real na validacao ponta a ponta da issue #44)
            previous = line
            line = re.sub(r"^-\s*", "", line)
            line = re.sub(r"^\[[ xX]?\]\s*", "", line)
            line = re.sub(r"^\d+[.)]\s*", "", line).strip()
        if line:
            items.append(line)
    return items[:4]


def _next_spec_number() -> int:
    numbers = []
    for path in _BUSINESS_SPECS_DIR.glob("*.md"):
        match = re.match(r"(\d+)-", path.name)
        if match:
            numbers.append(int(match.group(1)))
    return max(numbers, default=0) + 1


def _spec_slug(scenario_name: str) -> str:
    return scenario_name.replace("_", "-")


def _write_business_spec(
    finding: OpportunityFinding, resumo: str, contrato_afetado: str, criterio_items: list[str]
) -> Path:
    """Cria a spec de negocio de referencia da oportunidade em
    specs/business/, seguindo a mesma estrutura das specs ja existentes
    (issue #44) - o template business-story.md exige que a spec exista
    antes do inicio da implementacao."""
    _BUSINESS_SPECS_DIR.mkdir(parents=True, exist_ok=True)
    number = _next_spec_number()
    slug = _spec_slug(finding.scenario_name)
    path = _BUSINESS_SPECS_DIR / f"{number}-{slug}.md"
    titulo = finding.scenario_name.replace("_", " ").capitalize()
    criterio = "\n".join(f"- [ ] {item}" for item in criterio_items)
    content = f"""# {number} — {titulo}

## Contexto

{resumo}

Comportamento observado: {finding.observed_behavior}

## Objetivo

{contrato_afetado}

## Critério de aceite

{criterio}

## Sinal de risco

Categoria da mudança: regra de negócio
Serviço(s) afetado(s): a definir na triagem

## Dependências

Nenhuma.
"""
    path.write_text(content, encoding="utf-8")
    return path


def _commit_and_push_spec(spec_path: Path) -> None:
    """Commita e empurra a spec de negocio recem-criada direto para
    origin/main - o agent-local roda em um clone separado (v13/v14,
    agent-local/agent_local/git_ops.py: `git pull --ff-only` de main antes
    de criar branch), entao a spec precisa existir no remoto antes de a
    issue ser aberta, nao so localmente (issue #44)."""
    rel_path = spec_path.relative_to(_REPO_ROOT).as_posix()
    subprocess.run(["git", "add", rel_path], cwd=_REPO_ROOT, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"docs(specs): adicionar {rel_path}"],
        cwd=_REPO_ROOT,
        check=True,
    )
    subprocess.run(["git", "push", "origin", "main"], cwd=_REPO_ROOT, check=True)


def format_bug_issue(signal: BugSignal) -> tuple[str, str]:
    BUG_TEMPLATE_PATH.read_text(encoding="utf-8")  # confirma que o template existe/é lido
    raw = chat(_BUG_SYSTEM_PROMPT, f"Sinal detectado: {signal.signal_type} em {signal.service}. Detalhe: {signal.detail}")
    fields = _parse_fields(raw, "SINAL_QUE_DISPAROU", "EVIDENCIA")
    criticidade = SERVICE_CRITICALITY.get(signal.service, "baixo")

    aviso_caos = (
        "\n## ⚠️ Origem: camada de caos\n\n"
        f"`CHAOS_ENABLED=true` estava ativo em `{signal.service}` no momento da detecção — "
        "este sinal é falha simulada pela camada de caos "
        "(`specs/business/11-camada-caos.md`), não um bug de código. "
        "**Não deve ser corrigido automaticamente**: não há nada errado no código para reverter, "
        "e o middleware de caos está funcionando como esperado.\n"
        if signal.chaos_ativo
        else ""
    )

    title = f"[BUG] {signal.signal_type} em {signal.service}"
    body = f"""## Sinal que disparou

{fields['SINAL_QUE_DISPAROU'] or signal.detail}

## Serviço afetado

{signal.service} ({criticidade})

## Evidência

{fields['EVIDENCIA'] or signal.detail}

## Passos de reprodução (se aplicável)

Detectado automaticamente pelo agente preditivo via Prometheus/logs - sem passos manuais de reprodução.
{aviso_caos}
## Sinal de risco (para o score de subida)

Categoria da mudança: operacional
Serviço(s) afetado(s) e criticidade: {signal.service} ({criticidade})

## Dependências

Nenhuma.
"""
    return title, body


def format_opportunity_issue(finding: OpportunityFinding, scenario_path: Path | None) -> tuple[str, str, Path]:
    BUSINESS_STORY_TEMPLATE_PATH.read_text(encoding="utf-8")
    raw = chat(
        _OPORTUNIDADE_SYSTEM_PROMPT,
        f"Cenário: {finding.scenario_name}. Comportamento observado: {finding.observed_behavior}. "
        f"Racional do agente: {finding.racional}",
    )
    fields = _parse_fields(raw, "RESUMO", "CONTRATO_AFETADO", "SPECS_TECNICAS", "CRITERIO_ACEITE")

    resumo = fields["RESUMO"] or finding.racional
    contrato_afetado = fields["CONTRATO_AFETADO"] or finding.observed_behavior

    specs_relevantes = _parse_specs_tecnicas(fields["SPECS_TECNICAS"])
    specs_checklist = "\n".join(f"- [{'x' if spec in specs_relevantes else ' '}] {spec}" for spec in _TECH_SPECS)

    criterio_items = _parse_criterio_items(fields["CRITERIO_ACEITE"]) or [_GENERIC_CRITERIO_ITEM]
    criterio_checklist = "\n".join(f"- [ ] {item}" for item in criterio_items)

    spec_path = _write_business_spec(finding, resumo, contrato_afetado, criterio_items)
    spec_ref = f"`{spec_path.relative_to(_REPO_ROOT).as_posix()}`"
    scenario_ref = f"`{scenario_path.relative_to(_REPO_ROOT).as_posix()}`" if scenario_path else "(não salva)"

    title = f"[FASE 3] Oportunidade: {finding.scenario_name}"
    body = f"""## Spec de referência

{spec_ref}

Cenário reproduzível: {scenario_ref}

## Resumo

{resumo}

## Contrato afetado

{contrato_afetado}

## Critério de aceite

{criterio_checklist}

## Specs técnicas relevantes

{specs_checklist}

## Sinal de risco (para o score de subida)

Categoria da mudança: regra de negócio
Serviço(s) afetado(s) e criticidade: a definir na triagem

## Dependências

Nenhuma.
"""
    return title, body, spec_path


def create_issue(title: str, body: str, label: str, extra_labels: list[str] | None = None) -> tuple[int, str]:
    args = ["gh", "issue", "create", "--title", title, "--body", body, "--label", label]
    for extra_label in extra_labels or []:
        args += ["--label", extra_label]
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=True,
        cwd=_REPO_ROOT,
    )
    url = result.stdout.strip().splitlines()[-1]
    issue_number = int(url.rstrip("/").rsplit("/", 1)[-1])
    return issue_number, url


def register_bug(signal: BugSignal) -> int | None:
    existing = agent_ops_db.find_open_signal(signal.signal_type, signal.service)
    if existing is not None:
        logger.info(
            "Sinal já sinalizado e em aberto - issue não reaberta (dedup).",
            extra={
                "context": {
                    "signal_type": signal.signal_type,
                    "service": signal.service,
                    "issue_number": existing.get("issue_number"),
                }
            },
        )
        return None  # já sinalizado e em aberto - dedup, nao repete a acao

    title, body = format_bug_issue(signal)
    extra_labels = [CHAOS_ORIGIN_LABEL] if signal.chaos_ativo else None
    issue_number, url = create_issue(title, body, "bug", extra_labels=extra_labels)
    agent_ops_db.register_signal(signal.signal_type, signal.service, issue_number=issue_number)
    notify_issue_created(issue_number, title, "bug", url)
    logger.info(
        "Issue de bug criada.",
        extra={
            "context": {
                "issue_number": issue_number,
                "signal_type": signal.signal_type,
                "service": signal.service,
                "chaos_ativo": signal.chaos_ativo,
            }
        },
    )
    return issue_number


def register_opportunity(finding: OpportunityFinding, scenario_path: Path | None) -> int | None:
    if finding.veredito != "GAP":
        logger.info(
            "Cenário sem gap - nenhuma issue aberta.",
            extra={"context": {"scenario": finding.scenario_name, "veredito": finding.veredito}},
        )
        return None

    existing = agent_ops_db.find_open_signal(finding.scenario_name, "oportunidade")
    if existing is not None:
        logger.info(
            "Gap já sinalizado e em aberto - issue não reaberta (dedup).",
            extra={"context": {"scenario": finding.scenario_name, "issue_number": existing.get("issue_number")}},
        )
        return None

    title, body, spec_path = format_opportunity_issue(finding, scenario_path)
    _commit_and_push_spec(spec_path)
    issue_number, url = create_issue(title, body, "business-story")
    agent_ops_db.register_signal(finding.scenario_name, "oportunidade", issue_number=issue_number)
    notify_issue_created(issue_number, title, "business-story", url)
    logger.info(
        "Issue de oportunidade criada.",
        extra={"context": {"issue_number": issue_number, "scenario": finding.scenario_name}},
    )
    return issue_number
