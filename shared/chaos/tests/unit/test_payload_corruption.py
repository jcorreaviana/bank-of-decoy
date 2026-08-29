import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from chaos import ChaosMiddleware
from chaos import middleware as chaos_middleware
from chaos import payload_corruption
from chaos.runtime_config import clear_runtime_override, set_runtime_override


async def _account_detail(request):
    return JSONResponse({"id": "acc-1", "status": "ativa", "tipo_conta": "corrente", "saldo": 150.5})


async def _onboarding_internal(request):
    return JSONResponse(
        {
            "id": "onb-1",
            "cpf": "cipher",
            "status": "aprovado",
            "risco_cadastro": {"score": 0.42, "sinais": ["velocidade_alta"]},
        }
    )


async def _pix_key_lookup(request):
    return JSONResponse({"id": "pk-1", "account_id": "acc-1", "tipo": "email", "valor": "a@b.com", "ativa": False})


async def _post_transaction(request):
    return JSONResponse(
        {"id": "tx-1", "e2e_id": "e2e-1", "status": "processada", "risco_transacao": {"score": 0.1, "sinais": []}},
        status_code=201,
    )


async def _account_missing(request):
    return JSONResponse({"error_code": "ACCOUNT_NOT_FOUND", "message": "x", "field": None, "trace_id": "t"}, status_code=404)


def _build_app() -> Starlette:
    app = Starlette(
        routes=[
            Route("/v1/accounts/{account_id}", _account_detail),
            Route("/v1/onboarding/{onboarding_id}/internal", _onboarding_internal),
            Route("/v1/pix-keys/lookup", _pix_key_lookup),
            Route("/v1/transactions", _post_transaction, methods=["POST"]),
            Route("/v1/accounts/{account_id}/missing", _account_missing),
        ]
    )
    app.add_middleware(ChaosMiddleware)
    return app


@pytest.fixture(autouse=True)
def _force_payload_corrompido_sutil(monkeypatch):
    for key in ("CHAOS_ENABLED", "CHAOS_FAILURE_RATE", "CHAOS_FAILURE_TYPES"):
        monkeypatch.delenv(key, raising=False)
    clear_runtime_override()
    set_runtime_override(
        enabled=True, failure_rate=1.0, failure_types=["payload_corrompido_sutil"], duration_seconds=None
    )
    monkeypatch.setattr(chaos_middleware.random, "random", lambda: 0.0)
    monkeypatch.setattr(chaos_middleware.random, "choice", lambda choices: "payload_corrompido_sutil")
    yield
    clear_runtime_override()


def test_account_saldo_is_stringified():
    client = TestClient(_build_app())

    response = client.get("/v1/accounts/acc-1")

    assert response.status_code == 200
    body = response.json()
    assert body["saldo"] == "150.5"
    assert isinstance(body["saldo"], str)


def test_onboarding_internal_score_is_dropped():
    client = TestClient(_build_app())

    response = client.get("/v1/onboarding/onb-1/internal")

    assert response.status_code == 200
    body = response.json()
    assert "score" not in body["risco_cadastro"]
    assert body["risco_cadastro"]["sinais"] == ["velocidade_alta"]


def test_pix_key_lookup_ativa_is_forced_true():
    client = TestClient(_build_app())

    response = client.get("/v1/pix-keys/lookup")

    assert response.status_code == 200
    assert response.json()["ativa"] is True


def test_transaction_risco_score_is_stringified():
    client = TestClient(_build_app())

    response = client.post("/v1/transactions")

    assert response.status_code == 201
    assert response.json()["risco_transacao"]["score"] == "0.1"


def test_route_without_recipe_is_untouched():
    client = TestClient(_build_app())

    response = client.get("/v1/accounts/acc-1/missing")

    assert response.status_code == 404
    assert response.json() == {"error_code": "ACCOUNT_NOT_FOUND", "message": "x", "field": None, "trace_id": "t"}


def test_error_status_is_never_corrupted(monkeypatch):
    """Mesma rota de uma receita conhecida, mas simulando resposta de erro
    (>=300) - nao corrompe, mesmo com uma receita cadastrada para o path."""
    monkeypatch.setitem(
        payload_corruption._RECIPES,
        ("GET", "/v1/accounts/{account_id}/missing"),
        lambda body: payload_corruption._stringify_leaf(body, ["message"]),
    )
    client = TestClient(_build_app())

    response = client.get("/v1/accounts/acc-1/missing")

    assert response.status_code == 404
    assert response.json()["message"] == "x"


def test_stringify_leaf_is_noop_when_value_missing():
    data = {"a": {}}
    assert payload_corruption._stringify_leaf(data, ["a", "b"]) == {"a": {}}


def test_drop_leaf_is_noop_when_container_missing():
    data = {}
    assert payload_corruption._drop_leaf(data, ["a", "b"]) == {}


def test_force_leaf_sets_value_regardless_of_previous_value():
    assert payload_corruption._force_leaf({"ativa": False}, ["ativa"], True) == {"ativa": True}
    assert payload_corruption._force_leaf({"ativa": True}, ["ativa"], True) == {"ativa": True}
