"""Deteccao de oportunidade: RAG sobre specs/business/ + bateria de
cenarios sinteticos contra a API do ambiente efemero, julgamento via LLM
de cada par (regra recuperada, comportamento observado)
(specs/business/13-agente-preditivo-registro.md).

Auditoria de cobertura entre regra JA especificada e comportamento real
(docs/escopo-arquitetura.md, v14) - o LLM e instruido a so classificar
GAP quando a regra recuperada e explicita o suficiente para sustentar a
comparacao; ausencia de regra clara e sempre SEM_GAP, nunca "gap
provavel" inventado.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from agent_preditivo.config import get_settings
from agent_preditivo.llm import chat
from agent_preditivo.rag import search_specs
from agent_preditivo.scenarios import SCENARIOS, ScenarioResult

_SCENARIOS_DIR = Path(__file__).resolve().parents[2] / "tests" / "scenarios"

_SYSTEM_PROMPT = """Voce e um agente de auditoria de conformidade entre especificacoes de \
negocio e o comportamento real de um sistema bancario simulado. Voce recebe (1) o trecho \
de spec recuperado por busca semantica e (2) uma descricao do comportamento REAL observado \
ao executar uma chamada de API real contra o sistema.

Sua unica tarefa: decidir se o comportamento observado VIOLA uma regra EXPLICITAMENTE \
escrita no trecho de spec.

Regras estritas:
- So responda GAP se o trecho de spec afirmar claramente qual deveria ser o comportamento \
esperado, e o comportamento observado contradiz isso de forma inequivoca.
- Se o trecho de spec estiver vazio, for irrelevante, ou nao mencionar claramente essa \
situacao especifica, responda SEM_GAP - nunca invente uma regra que nao esta escrita.
- Nao sugira o que "deveria" ser a regra caso ela nao exista - isso nao e este agente \
(fica para uma fase futura de descoberta de padrao de negocio).

Responda EXATAMENTE neste formato, nada mais:
VEREDITO: GAP ou SEM_GAP
RACIONAL: <uma frase curta explicando a decisao>
"""


@dataclass(frozen=True)
class OpportunityFinding:
    scenario_name: str
    veredito: str  # "GAP" ou "SEM_GAP"
    racional: str
    observed_behavior: str
    rule_chunks: list[dict]


def _judge(scenario: ScenarioResult) -> OpportunityFinding:
    rule_chunks = search_specs(scenario.rule_query)
    contexto_specs = (
        "\n---\n".join(f"(arquivo: {c['file']}, secao: {c['section']}) {c['text']}" for c in rule_chunks)
        if rule_chunks
        else "(nenhum trecho de spec suficientemente relevante encontrado)"
    )

    user_message = (
        f"Trecho de spec recuperado:\n{contexto_specs}\n\n"
        f"Comportamento observado ao executar o cenario '{scenario.name}':\n{scenario.observed_behavior}"
    )

    raw = chat(_SYSTEM_PROMPT, user_message, temperature=0.0)
    veredito_match = re.search(r"VEREDITO:\s*(GAP|SEM_GAP)", raw)
    racional_match = re.search(r"RACIONAL:\s*(.+)", raw, re.DOTALL)

    veredito = veredito_match.group(1) if veredito_match else "SEM_GAP"
    racional = racional_match.group(1).strip() if racional_match else raw.strip()

    return OpportunityFinding(
        scenario_name=scenario.name,
        veredito=veredito,
        racional=racional,
        observed_behavior=scenario.observed_behavior,
        rule_chunks=rule_chunks,
    )


def run_opportunity_battery(api_base_urls: dict[str, str] | None = None) -> list[OpportunityFinding]:
    api_base_urls = api_base_urls or get_settings().api_base_urls
    findings = []
    for scenario_fn in SCENARIOS:
        result = scenario_fn(api_base_urls)
        findings.append(_judge(result))
    return findings


def save_scenario_journey(finding: OpportunityFinding, steps: list[str]) -> Path:
    """Salva a jornada reproduzivel de um gap encontrado em
    tests/scenarios/ (formato Markdown simples, reexecutavel por humano ou
    outro agente) - specs/business/13-agente-preditivo-registro.md."""
    _SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
    path = _SCENARIOS_DIR / f"{finding.scenario_name}.md"
    content = (
        f"# Cenário: {finding.scenario_name}\n\n"
        f"## Veredito\n{finding.veredito}\n\n"
        f"## Racional\n{finding.racional}\n\n"
        f"## Comportamento observado\n{finding.observed_behavior}\n\n"
        f"## Passos de reprodução\n"
        + "\n".join(f"{i + 1}. {step}" for i, step in enumerate(steps))
        + "\n"
    )
    path.write_text(content, encoding="utf-8")
    return path
