"""Score de risco de subida - formula definida em docs/escopo-arquitetura.md
(secao "Score de risco de subida"), specs/business/14-agente-local.md.

## Formato esperado dos campos na issue

Le a secao `## Sinal de risco (para o score de subida)` do corpo da issue
(mesmo padrao usado em toda issue criada neste projeto ate aqui, ex.
issues #15/#16/#17/#18):

    Categoria da mudança: regra de negócio | operacional
    Serviço(s) afetado(s) e criticidade: <texto livre contendo "crítico",
        "alto" ou "baixo" em algum lugar - ex. "transaction-service
        (crítico)" ou "novo componente, criticidade: crítico">

Campo ausente ou nao reconhecido: NAO quebra o processo (specs/business/14),
mas usa o default mais CONSERVADOR (empurra para revisao humana), nunca o
mais permissivo - errar para o lado seguro quando o dado esta malformado:
- Categoria ausente/nao reconhecida -> "regra_de_negocio" (eleva o score).
- Criticidade ausente/nao reconhecida -> "critico" (menor threshold).
"""

import re
from dataclasses import dataclass

CRITICALITY_WEIGHT = {"critico": 40, "alto": 30, "baixo": 10}
"""Pesos ja definidos literalmente em docs/escopo-arquitetura.md (nao
inventados aqui)."""

CATEGORY_MULTIPLIER = {"regra_de_negocio": 1.3, "operacional": 0.7}
"""Moduladores do total (nao soma linear - docs/escopo-arquitetura.md:
"regra de negocio... eleva o score... operacional... reduz o score").
Valores exatos nao definidos no documento ("a definir... quando houver
dados reais de execucao") - v1 documentado aqui, +30%/-30%, recalibravel
com dados reais de execucao."""

COVERAGE_MAX_PENALTY = 20.0
DIFF_MAX_PENALTY = 20.0
DIFF_SATURATION_LINES = 500
"""Pesos secundarios (docs/escopo-arquitetura.md: "criticidade do servico
> cobertura ~= diff") - v1: metade do peso maximo da criticidade critica
(40), cobertura e diff empatados entre si. Diff satura em 500 linhas
alteradas (git diff --stat) - acima disso, mesmo score de diff."""

THRESHOLD_BY_CRITICALITY = {"critico": 20, "alto": 40, "baixo": 65}
"""Threshold de autonomia por tier (docs/escopo-arquitetura.md: "quanto
mais critico... mais rigoroso (menor) o threshold"). Valores nao definidos
no documento - v1 documentado aqui, recalibravel com dados reais."""

_SINAL_RISCO_SECTION = re.compile(
    r"##\s*Sinal de risco.*?\n(.*?)(?:\n##|\Z)", re.DOTALL | re.IGNORECASE
)
_CATEGORIA_NEGOCIO = re.compile(r"regra de neg[oó]cio", re.IGNORECASE)
_CATEGORIA_OPERACIONAL = re.compile(r"operacional", re.IGNORECASE)
_CRITICIDADE_CRITICO = re.compile(r"cr[ií]tico", re.IGNORECASE)
_CRITICIDADE_ALTO = re.compile(r"\balto\b", re.IGNORECASE)
_CRITICIDADE_BAIXO = re.compile(r"\bbaixo\b", re.IGNORECASE)

DEFAULT_CATEGORY = "regra_de_negocio"
DEFAULT_CRITICALITY = "critico"


@dataclass(frozen=True)
class RiskFields:
    category: str  # "regra_de_negocio" | "operacional"
    criticality: str  # "critico" | "alto" | "baixo"
    category_parsed: bool
    criticality_parsed: bool


@dataclass(frozen=True)
class RiskScoreResult:
    score: float
    threshold: float
    decision: str  # "autonomo" | "humano"
    risk_fields: RiskFields
    coverage_fraction: float
    diff_lines: int


def parse_risk_fields(issue_body: str) -> RiskFields:
    section_match = _SINAL_RISCO_SECTION.search(issue_body)
    section_text = section_match.group(1) if section_match else ""

    if _CATEGORIA_NEGOCIO.search(section_text):
        category, category_parsed = "regra_de_negocio", True
    elif _CATEGORIA_OPERACIONAL.search(section_text):
        category, category_parsed = "operacional", True
    else:
        category, category_parsed = DEFAULT_CATEGORY, False

    if _CRITICIDADE_CRITICO.search(section_text):
        criticality, criticality_parsed = "critico", True
    elif _CRITICIDADE_ALTO.search(section_text):
        criticality, criticality_parsed = "alto", True
    elif _CRITICIDADE_BAIXO.search(section_text):
        criticality, criticality_parsed = "baixo", True
    else:
        criticality, criticality_parsed = DEFAULT_CRITICALITY, False

    return RiskFields(
        category=category,
        criticality=criticality,
        category_parsed=category_parsed,
        criticality_parsed=criticality_parsed,
    )


def calculate_risk_score(issue_body: str, coverage_fraction: float, diff_lines: int) -> RiskScoreResult:
    """`coverage_fraction`: 0.0-1.0 (cobertura do trecho alterado, de
    pytest --cov). `diff_lines`: total de linhas alteradas (git diff --stat,
    soma de inseridas + removidas)."""
    risk_fields = parse_risk_fields(issue_body)

    criticidade_peso = CRITICALITY_WEIGHT[risk_fields.criticality]
    cobertura_penalidade = (1.0 - min(max(coverage_fraction, 0.0), 1.0)) * COVERAGE_MAX_PENALTY
    diff_penalidade = min(diff_lines / DIFF_SATURATION_LINES, 1.0) * DIFF_MAX_PENALTY

    score_base = criticidade_peso + cobertura_penalidade + diff_penalidade
    score = min(score_base * CATEGORY_MULTIPLIER[risk_fields.category], 100.0)

    threshold = THRESHOLD_BY_CRITICALITY[risk_fields.criticality]
    decision = "autonomo" if score < threshold else "humano"

    return RiskScoreResult(
        score=round(score, 2),
        threshold=threshold,
        decision=decision,
        risk_fields=risk_fields,
        coverage_fraction=coverage_fraction,
        diff_lines=diff_lines,
    )
