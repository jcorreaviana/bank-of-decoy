import uuid
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.main import app

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.database_url,
    reason="DATABASE_URL nao configurada - teste de contrato de transactions requer banco real.",
)


@pytest.fixture(autouse=True)
def _clean_transactions_table():
    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE transactions"))
    yield
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE transactions"))


def _mock_account_response(status_code: int, **overrides) -> httpx.Response:
    payload = {
        "id": str(uuid.uuid4()),
        "status": "ativa",
        "tipo_conta": "corrente",
        "created_at": "2026-01-01T00:00:00.000Z",
    }
    payload.update(overrides)
    return httpx.Response(status_code, json=payload)


def _patch_account_get(response: httpx.Response | None = None, side_effect=None):
    target = "app.services.account_client.httpx.get"
    if side_effect is not None:
        return patch(target, side_effect=side_effect)
    return patch(target, return_value=response)


def _payload(**overrides) -> dict:
    base = {"account_id": str(uuid.uuid4()), "pix_key_destino": "destino@example.com", "valor": 100.0}
    base.update(overrides)
    return base


def test_post_transaction_happy_path_returns_201() -> None:
    client = TestClient(app)
    account_id = str(uuid.uuid4())

    with _patch_account_get(_mock_account_response(200, id=account_id)):
        response = client.post("/v1/transactions", json=_payload(account_id=account_id))

    assert response.status_code == 201
    body = response.json()
    assert body["status"] in ("concluida", "suspeita")
    assert isinstance(body["risco_transacao"]["score"], (int, float))
    assert isinstance(body["risco_transacao"]["sinais"], list)
    assert "id" in body
    assert "created_at" in body


def test_post_transaction_valor_atipico_para_destinatario_novo_resulta_suspeita() -> None:
    client = TestClient(app)
    account_id = str(uuid.uuid4())

    with _patch_account_get(_mock_account_response(200, id=account_id)):
        response = client.post(
            "/v1/transactions",
            json=_payload(account_id=account_id, valor=25_000.0, pix_key_destino="novo-destino@example.com"),
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "suspeita"
    assert "valor_atipico" in body["risco_transacao"]["sinais"]
    assert "destinatario_novo" in body["risco_transacao"]["sinais"]


def test_post_transaction_valor_zero_returns_400() -> None:
    client = TestClient(app)

    response = client.post("/v1/transactions", json=_payload(valor=0))

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["field"] == "valor"


def test_post_transaction_valor_negativo_returns_400() -> None:
    client = TestClient(app)

    response = client.post("/v1/transactions", json=_payload(valor=-10))

    assert response.status_code == 400
    assert response.json()["error_code"] == "VALIDATION_ERROR"


def test_post_transaction_pix_key_destino_vazio_returns_400() -> None:
    client = TestClient(app)

    response = client.post("/v1/transactions", json=_payload(pix_key_destino="   "))

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["field"] == "pix_key_destino"


def test_post_transaction_conta_nao_ativa_returns_422() -> None:
    client = TestClient(app)

    with _patch_account_get(_mock_account_response(200, status="bloqueada")):
        response = client.post("/v1/transactions", json=_payload())

    assert response.status_code == 422
    assert response.json()["error_code"] == "ACCOUNT_NOT_ACTIVE"


def test_post_transaction_conta_inexistente_returns_422() -> None:
    client = TestClient(app)
    not_found = httpx.Response(
        404, json={"error_code": "ACCOUNT_NOT_FOUND", "message": "x", "field": None, "trace_id": "y"}
    )

    with _patch_account_get(not_found):
        response = client.post("/v1/transactions", json=_payload())

    assert response.status_code == 422
    assert response.json()["error_code"] == "ACCOUNT_NOT_ACTIVE"


def test_post_transaction_account_service_unavailable_returns_500_without_leaking_details() -> None:
    client = TestClient(app, raise_server_exceptions=False)

    with _patch_account_get(side_effect=httpx.ConnectError("connection refused to 10.0.0.1:8002")):
        response = client.post("/v1/transactions", json=_payload())

    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "INTERNAL_ERROR"
    assert "10.0.0.1" not in body["message"]
    assert "httpx" not in body["message"].lower()
