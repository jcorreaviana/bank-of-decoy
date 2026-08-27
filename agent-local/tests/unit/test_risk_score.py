from agent_local.risk_score import (
    CATEGORY_MULTIPLIER,
    CRITICALITY_WEIGHT,
    THRESHOLD_BY_CRITICALITY,
    calculate_risk_score,
    parse_risk_fields,
)

_ISSUE_CRITICO_NEGOCIO = """
## Sinal de risco (para o score de subida)

Categoria da mudança: regra de negócio
Serviço(s) afetado(s) e criticidade: transaction-service (crítico)

## Dependências

Nenhuma.
"""

_ISSUE_BAIXO_OPERACIONAL = """
## Sinal de risco (para o score de subida)

Categoria da mudança: operacional
Serviço(s) afetado(s) e criticidade: infraestrutura/observabilidade (baixo)

## Dependências

Nenhuma.
"""

_ISSUE_SEM_SECAO = "## Resumo\n\nSem secao de sinal de risco nenhuma."


def test_parse_risk_fields_critico_negocio() -> None:
    fields = parse_risk_fields(_ISSUE_CRITICO_NEGOCIO)
    assert fields.category == "regra_de_negocio"
    assert fields.criticality == "critico"
    assert fields.category_parsed is True
    assert fields.criticality_parsed is True


def test_parse_risk_fields_baixo_operacional() -> None:
    fields = parse_risk_fields(_ISSUE_BAIXO_OPERACIONAL)
    assert fields.category == "operacional"
    assert fields.criticality == "baixo"


def test_parse_risk_fields_secao_ausente_usa_defaults_conservadores() -> None:
    fields = parse_risk_fields(_ISSUE_SEM_SECAO)
    assert fields.category == "regra_de_negocio"
    assert fields.criticality == "critico"
    assert fields.category_parsed is False
    assert fields.criticality_parsed is False


def test_calculate_risk_score_bate_com_a_formula_cobertura_alta_diff_pequeno() -> None:
    result = calculate_risk_score(_ISSUE_CRITICO_NEGOCIO, coverage_fraction=1.0, diff_lines=10)

    esperado_base = CRITICALITY_WEIGHT["critico"] + 0.0 + (10 / 500) * 20.0
    esperado_score = round(esperado_base * CATEGORY_MULTIPLIER["regra_de_negocio"], 2)

    assert result.score == esperado_score
    assert result.threshold == THRESHOLD_BY_CRITICALITY["critico"]


def test_calculate_risk_score_operacional_baixo_cobertura_total_fica_bem_abaixo() -> None:
    result = calculate_risk_score(_ISSUE_BAIXO_OPERACIONAL, coverage_fraction=1.0, diff_lines=0)

    esperado_score = round(CRITICALITY_WEIGHT["baixo"] * CATEGORY_MULTIPLIER["operacional"], 2)
    assert result.score == esperado_score
    assert result.decision == "autonomo"


def test_calculate_risk_score_sem_cobertura_aumenta_score() -> None:
    com_cobertura = calculate_risk_score(_ISSUE_CRITICO_NEGOCIO, coverage_fraction=1.0, diff_lines=0)
    sem_cobertura = calculate_risk_score(_ISSUE_CRITICO_NEGOCIO, coverage_fraction=0.0, diff_lines=0)

    assert sem_cobertura.score > com_cobertura.score


def test_calculate_risk_score_diff_grande_aumenta_score_ate_saturar() -> None:
    diff_medio = calculate_risk_score(_ISSUE_CRITICO_NEGOCIO, coverage_fraction=1.0, diff_lines=250)
    diff_saturado = calculate_risk_score(_ISSUE_CRITICO_NEGOCIO, coverage_fraction=1.0, diff_lines=500)
    diff_alem_da_saturacao = calculate_risk_score(_ISSUE_CRITICO_NEGOCIO, coverage_fraction=1.0, diff_lines=5000)

    assert diff_medio.score < diff_saturado.score
    assert diff_saturado.score == diff_alem_da_saturacao.score


def test_calculate_risk_score_score_nunca_ultrapassa_100() -> None:
    result = calculate_risk_score(_ISSUE_CRITICO_NEGOCIO, coverage_fraction=0.0, diff_lines=10_000)
    assert result.score <= 100.0


def test_calculate_risk_score_decisao_autonoma_quando_score_abaixo_do_threshold() -> None:
    result = calculate_risk_score(_ISSUE_BAIXO_OPERACIONAL, coverage_fraction=1.0, diff_lines=5)
    assert result.decision == "autonomo"


def test_calculate_risk_score_decisao_humana_quando_score_acima_do_threshold() -> None:
    result = calculate_risk_score(_ISSUE_CRITICO_NEGOCIO, coverage_fraction=0.0, diff_lines=1000)
    assert result.decision == "humano"


def test_threshold_mais_rigoroso_quanto_mais_critico() -> None:
    assert THRESHOLD_BY_CRITICALITY["critico"] < THRESHOLD_BY_CRITICALITY["alto"] < THRESHOLD_BY_CRITICALITY["baixo"]
