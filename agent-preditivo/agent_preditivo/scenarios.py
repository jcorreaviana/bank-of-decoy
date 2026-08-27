"""Bateria de cenarios sinteticos do agente de oportunidade - cada cenario
executa uma sequencia de chamadas reais contra a API do ambiente efemero
(docker-compose.test.yml) e descreve o comportamento observado em
linguagem natural, para o agente comparar contra a regra recuperada via
RAG (specs/business/13-agente-preditivo-registro.md).

Os dois exemplos originais da spec (saldo insuficiente, chave cancelada)
foram corrigidos nas issues #17/#18 - ja sao regras que existem, nao gaps.
Cenarios abaixo cobrem terreno novo (2025-08-27, retomada da issue #15).
"""

import uuid
from dataclasses import dataclass

import httpx

_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    rule_query: str
    """Texto usado para buscar a regra relevante via RAG (search_specs)."""
    observed_behavior: str
    """Descricao em linguagem natural do que a API realmente fez."""
    passed_baseline: bool | None
    """Quando o proprio cenario ja sabe o status esperado (ex. contrato
    documentado), True/False se bateu; None quando o cenario nao tem
    certeza a priori e depende do julgamento via RAG+LLM."""


def scenario_onboarding_get_inexistente(api_base_urls: dict[str, str]) -> ScenarioResult:
    onboarding_id = uuid.uuid4()
    response = httpx.get(f"{api_base_urls['onboarding-service']}/v1/onboarding/{onboarding_id}", timeout=_TIMEOUT_SECONDS)
    body = _safe_json(response)
    observed = (
        f"GET /v1/onboarding/{{id inexistente}} retornou {response.status_code}, "
        f"error_code={body.get('error_code')}"
    )
    esperado_ok = response.status_code == 404 and body.get("error_code") == "ONBOARDING_NOT_FOUND"
    return ScenarioResult(
        name="onboarding_get_inexistente",
        rule_query="GET /v1/onboarding/{id} para id inexistente deve retornar 404 ONBOARDING_NOT_FOUND",
        observed_behavior=observed,
        passed_baseline=esperado_ok,
    )


def scenario_account_post_onboarding_inexistente(api_base_urls: dict[str, str]) -> ScenarioResult:
    onboarding_id = uuid.uuid4()
    response = httpx.post(
        f"{api_base_urls['account-service']}/v1/accounts",
        json={"onboarding_id": str(onboarding_id), "tipo_conta": "corrente"},
        timeout=_TIMEOUT_SECONDS,
    )
    body = _safe_json(response)
    observed = (
        f"POST /v1/accounts com onboarding_id inexistente retornou {response.status_code}, "
        f"error_code={body.get('error_code')}"
    )
    esperado_ok = response.status_code == 404 and body.get("error_code") == "ONBOARDING_NOT_FOUND"
    return ScenarioResult(
        name="account_post_onboarding_inexistente",
        rule_query="POST /v1/accounts com onboarding_id inexistente deve retornar 404 ONBOARDING_NOT_FOUND",
        observed_behavior=observed,
        passed_baseline=esperado_ok,
    )


def scenario_pix_key_conta_inexistente(api_base_urls: dict[str, str]) -> ScenarioResult:
    """Nenhum criterio de aceite numerado em specs/business/06 exige
    validar a existencia da conta ao criar uma chave PIX - cenario
    deliberadamente aberto, para testar se o RAG encontra (ou nao) uma
    regra que sustente classificar isso como gap."""
    account_id = uuid.uuid4()
    valor = f"cenario-{uuid.uuid4()}@example.com"
    response = httpx.post(
        f"{api_base_urls['pix-key-service']}/v1/pix-keys",
        json={"account_id": str(account_id), "tipo": "email", "valor": valor},
        timeout=_TIMEOUT_SECONDS,
    )
    body = _safe_json(response)
    observed = (
        f"POST /v1/pix-keys com account_id ({account_id}) que nunca existiu em account-service "
        f"retornou {response.status_code} ({'chave criada' if response.status_code == 201 else body.get('error_code')})"
    )
    return ScenarioResult(
        name="pix_key_conta_inexistente",
        rule_query="POST /v1/pix-keys deve validar que account_id existe antes de criar a chave",
        observed_behavior=observed,
        passed_baseline=None,
    )


def _safe_json(response: httpx.Response) -> dict:
    try:
        return response.json()
    except Exception:
        return {}


SCENARIOS = [
    scenario_onboarding_get_inexistente,
    scenario_account_post_onboarding_inexistente,
    scenario_pix_key_conta_inexistente,
]
