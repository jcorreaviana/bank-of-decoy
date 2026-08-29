"""Agente de registro (Modelo B): mesmo modelo `llama3.2:3b`, prompt
tecnico/negocio montado dinamicamente a partir da leitura direta do template
de issue correspondente ("RAG" simplificado - um documento curto de ~30
linhas nao justifica indexacao vetorial; decisao documentada, mesma
filosofia de manter cada peca no tamanho certo). As secoes do template
guiam tanto o que e pedido ao LLM quanto a estrutura do corpo final, para
que editar o .md nao exija tocar neste modulo (issue #45). Preenche os
campos de risco em codigo (nao pelo LLM - mesma filosofia de nao delegar
decisao estruturada ao modelo usada no resto do projeto), cria a issue via
`gh issue create` e registra em `flagged_signals`
(specs/business/13-agente-preditivo-registro.md).
"""

import logging
import re
import subprocess
import unicodedata
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

_GENERIC_CRITERIO_ITEM = "A definir após triagem humana/agente local"

_BUSINESS_SPECS_DIR = _REPO_ROOT / "specs" / "business"

# Chaves normalizadas (via _normalize_header) das secoes dos templates que o
# codigo sabe computar - as demais viram narrativa generica pedida ao LLM
# usando o proprio texto-guia do template, sem exigir edicao aqui (issue #45).
_KEY_SINAL_RISCO = "sinal de risco"
_KEY_DEPENDENCIAS = "dependencias"

_BUG_KEY_SINAL = "sinal que disparou"
_BUG_KEY_SERVICO = "servico afetado"
_BUG_KEY_EVIDENCIA = "evidencia"
_BUG_KEY_PASSOS = "passos de reproducao"

_BUSINESS_KEY_SPEC_REF = "spec de referencia"
_BUSINESS_KEY_RESUMO = "resumo"
_BUSINESS_KEY_CONTRATO = "contrato afetado"
_BUSINESS_KEY_CRITERIO = "criterio de aceite"
_BUSINESS_KEY_SPECS_TEC = "specs tecnicas relevantes"


def _parse_template_sections(path: Path) -> list[tuple[str, str]]:
    """Le um template de issue (.github/ISSUE_TEMPLATE/*.md) e devolve suas
    secoes "## Titulo" na ordem em que aparecem, cada uma com o texto-guia
    (orientacao para quem preenche) logo abaixo do titulo - fonte real da
    estrutura da issue, para nao duplicar em system prompts fixos (issue #45)."""
    text = path.read_text(encoding="utf-8")
    parts = re.split(r"^##[ \t]+(.+?)[ \t]*$", text, flags=re.MULTILINE)
    sections = []
    for i in range(1, len(parts), 2):
        header = parts[i].strip()
        content = parts[i + 1].strip() if i + 1 < len(parts) else ""
        sections.append((header, content))
    return sections


def _normalize_header(header: str) -> str:
    """Chave de identificacao de uma secao, tolerante a qualificadores entre
    parenteses e acentos (ex. "Evidência" e "Sinal de risco (para o score de
    subida)" viram "evidencia" e "sinal de risco"), usada para casar secoes
    do template com o codigo que sabe computa-las."""
    base = header.split("(", 1)[0].strip().lower()
    return unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")


def _header_field_name(normalized_header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", normalized_header).strip("_").upper()


def _default_categoria(guidance: str) -> str:
    """Extrai o valor-padrao de "Categoria da mudança" do texto-guia da
    secao "Sinal de risco" do template (ex. "operacional (a maioria dos...)"
    ou "regra de negócio | operacional" -> usa a primeira opcao)."""
    match = re.search(r"Categoria da mudança:\s*([^\n(|]+)", guidance)
    return match.group(1).strip() if match else ""


def _parse_fields(raw: str, *field_names: str) -> dict[str, str]:
    fields = {}
    for name in field_names:
        match = re.search(rf"{name}:\s*(.+?)(?=\n[A-Z_]+:|$)", raw, re.DOTALL)
        fields[name] = match.group(1).strip() if match else ""
    return fields


def _parse_checklist_items(guidance: str) -> list[str]:
    """Extrai os itens "- [ ] item" do texto-guia de uma secao do template
    (ex. a lista de specs tecnicas em business-story.md), na ordem em que
    aparecem - fonte real da lista, para nao duplica-la em codigo (issue #45)."""
    return re.findall(r"^-\s*\[[ xX]?\]\s*(.+?)\s*$", guidance, flags=re.MULTILINE)


def _parse_specs_tecnicas(raw_field: str, specs_validas: list[str]) -> list[str]:
    if not raw_field:
        return []
    candidatos = {item.strip().lower() for item in raw_field.split(",")}
    return [spec for spec in specs_validas if spec.lower() in candidatos]


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
    sections = _parse_template_sections(BUG_TEMPLATE_PATH)
    criticidade = SERVICE_CRITICALITY.get(signal.service, "baixo")

    llm_lines = []
    generic_fields: list[str] = []
    for header, guidance in sections:
        key = _normalize_header(header)
        if key == _BUG_KEY_SINAL:
            llm_lines.append(f"SINAL_QUE_DISPAROU: <uma ou duas frases, em portugues, com base em: {guidance}>")
        elif key == _BUG_KEY_EVIDENCIA:
            llm_lines.append(f"EVIDENCIA: <trecho ou resumo curto, em portugues, com base em: {guidance}>")
        elif key in {_BUG_KEY_SERVICO, _BUG_KEY_PASSOS, _KEY_SINAL_RISCO, _KEY_DEPENDENCIAS}:
            continue  # computadas em codigo a partir do sinal, nao vao ao LLM
        else:
            # secao nova, sem tratamento conhecido no codigo: narrativa livre
            # a partir do proprio texto-guia do template (issue #45)
            field = _header_field_name(key)
            llm_lines.append(f"{field}: <uma ou duas frases, em portugues, com base em: {guidance}>")
            generic_fields.append(field)

    system_prompt = (
        "Voce e o agente de registro tecnico de um sistema de monitoramento bancario. Escreva, em "
        "portugues, o conteudo das secoes abaixo para uma issue de bug, com base no sinal detectado "
        "que sera descrito pelo usuario. Responda em EXATAMENTE este formato, nada antes nem depois:\n\n"
        + "\n".join(llm_lines)
    )
    raw = chat(system_prompt, f"Sinal detectado: {signal.signal_type} em {signal.service}. Detalhe: {signal.detail}")
    fields = _parse_fields(raw, "SINAL_QUE_DISPAROU", "EVIDENCIA", *generic_fields)

    aviso_caos = (
        "## ⚠️ Origem: camada de caos\n\n"
        f"`CHAOS_ENABLED=true` estava ativo em `{signal.service}` no momento da detecção — "
        "este sinal é falha simulada pela camada de caos "
        "(`specs/business/11-camada-caos.md`), não um bug de código. "
        "**Não deve ser corrigido automaticamente**: não há nada errado no código para reverter, "
        "e o middleware de caos está funcionando como esperado."
        if signal.chaos_ativo
        else ""
    )

    body_parts = []
    for header, guidance in sections:
        key = _normalize_header(header)
        if key == _BUG_KEY_SINAL:
            content = fields["SINAL_QUE_DISPAROU"] or signal.detail
        elif key == _BUG_KEY_SERVICO:
            content = f"{signal.service} ({criticidade})"
        elif key == _BUG_KEY_EVIDENCIA:
            content = fields["EVIDENCIA"] or signal.detail
        elif key == _BUG_KEY_PASSOS:
            content = (
                "Detectado automaticamente pelo agente preditivo via Prometheus/logs - "
                "sem passos manuais de reprodução."
            )
        elif key == _KEY_SINAL_RISCO:
            categoria = _default_categoria(guidance) or "operacional"
            content = (
                f"Categoria da mudança: {categoria}\n"
                f"Serviço(s) afetado(s) e criticidade: {signal.service} ({criticidade})"
            )
        elif key == _KEY_DEPENDENCIAS:
            content = "Nenhuma."
        else:
            content = fields.get(_header_field_name(key), "")
        body_parts.append(f"## {header}\n\n{content}")
        if key == _BUG_KEY_PASSOS and aviso_caos:
            body_parts.append(aviso_caos)

    title = f"[BUG] {signal.signal_type} em {signal.service}"
    body = "\n\n".join(body_parts) + "\n"
    return title, body


def format_opportunity_issue(finding: OpportunityFinding, scenario_path: Path | None) -> tuple[str, str, Path]:
    sections = _parse_template_sections(BUSINESS_STORY_TEMPLATE_PATH)

    specs_validas: list[str] = []
    llm_lines = []
    generic_fields: list[str] = []
    for header, guidance in sections:
        key = _normalize_header(header)
        if key == _BUSINESS_KEY_RESUMO:
            llm_lines.append(
                "RESUMO: <uma ou duas frases, em portugues, resumindo a lacuna encontrada em "
                f"linguagem de negocio, com base em: {guidance}>"
            )
        elif key == _BUSINESS_KEY_CONTRATO:
            llm_lines.append(
                "CONTRATO_AFETADO: <qual contrato/regra de negocio o comportamento observado nao "
                f"respeita, com base em: {guidance}>"
            )
        elif key == _BUSINESS_KEY_SPECS_TEC:
            specs_validas = _parse_checklist_items(guidance)
            llm_lines.append(
                "SPECS_TECNICAS: <lista separada por virgula, somente com nomes exatos dentre: "
                + ", ".join(specs_validas)
                + " - inclua so as realmente relevantes para esse achado especifico, ou \"nenhuma\" "
                "se nenhuma se aplicar>"
            )
        elif key == _BUSINESS_KEY_CRITERIO:
            llm_lines.append(
                "CRITERIO_ACEITE: <entre 2 e 4 itens verificaveis reais derivados do achado, um por "
                "linha, cada linha comecando com \"- \", sem numeracao, no mesmo estilo do exemplo do "
                f"template:\n{guidance}>"
            )
        elif key in {_BUSINESS_KEY_SPEC_REF, _KEY_SINAL_RISCO, _KEY_DEPENDENCIAS}:
            continue  # computadas em codigo (spec criada, risco, dependencias), nao vao ao LLM
        else:
            # secao nova, sem tratamento conhecido no codigo: narrativa livre
            # a partir do proprio texto-guia do template (issue #45)
            field = _header_field_name(key)
            llm_lines.append(f"{field}: <uma ou duas frases, em portugues, com base em: {guidance}>")
            generic_fields.append(field)

    system_prompt = (
        "Voce e o agente de registro de negocio de um sistema bancario. Escreva, em portugues, o "
        "conteudo das secoes abaixo para uma issue de oportunidade (lacuna entre regra ja "
        "especificada e comportamento real), com base no achado que sera descrito pelo usuario. "
        "Responda em EXATAMENTE este formato, nada antes nem depois:\n\n" + "\n".join(llm_lines)
    )
    raw = chat(
        system_prompt,
        f"Cenário: {finding.scenario_name}. Comportamento observado: {finding.observed_behavior}. "
        f"Racional do agente: {finding.racional}",
    )
    fields = _parse_fields(raw, "RESUMO", "CONTRATO_AFETADO", "SPECS_TECNICAS", "CRITERIO_ACEITE", *generic_fields)

    resumo = fields["RESUMO"] or finding.racional
    contrato_afetado = fields["CONTRATO_AFETADO"] or finding.observed_behavior

    specs_relevantes = _parse_specs_tecnicas(fields["SPECS_TECNICAS"], specs_validas)
    specs_checklist = "\n".join(f"- [{'x' if spec in specs_relevantes else ' '}] {spec}" for spec in specs_validas)

    criterio_items = _parse_criterio_items(fields["CRITERIO_ACEITE"]) or [_GENERIC_CRITERIO_ITEM]
    criterio_checklist = "\n".join(f"- [ ] {item}" for item in criterio_items)

    spec_path = _write_business_spec(finding, resumo, contrato_afetado, criterio_items)
    spec_ref = f"`{spec_path.relative_to(_REPO_ROOT).as_posix()}`"
    scenario_ref = f"`{scenario_path.relative_to(_REPO_ROOT).as_posix()}`" if scenario_path else "(não salva)"

    body_parts = []
    for header, guidance in sections:
        key = _normalize_header(header)
        if key == _BUSINESS_KEY_SPEC_REF:
            content = f"{spec_ref}\n\nCenário reproduzível: {scenario_ref}"
        elif key == _BUSINESS_KEY_RESUMO:
            content = resumo
        elif key == _BUSINESS_KEY_CONTRATO:
            content = contrato_afetado
        elif key == _BUSINESS_KEY_CRITERIO:
            content = criterio_checklist
        elif key == _BUSINESS_KEY_SPECS_TEC:
            content = specs_checklist
        elif key == _KEY_SINAL_RISCO:
            categoria = _default_categoria(guidance) or "regra de negócio"
            content = f"Categoria da mudança: {categoria}\nServiço(s) afetado(s) e criticidade: a definir na triagem"
        elif key == _KEY_DEPENDENCIAS:
            content = "Nenhuma."
        else:
            content = fields.get(_header_field_name(key), "")
        body_parts.append(f"## {header}\n\n{content}")

    title = f"[FASE 3] Oportunidade: {finding.scenario_name}"
    body = "\n\n".join(body_parts) + "\n"
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
