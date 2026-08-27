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


def _mock_pix_key_response(status_code: int, **overrides) -> httpx.Response:
    payload = {
        "id": str(uuid.uuid4()),
        "account_id": str(uuid.uuid4()),
        "tipo": "email",
        "valor": "destino@example.com",
        "ativa": True,
    }
    payload.update(overrides)
    return httpx.Response(status_code, json=payload)


def _patch_upstream_calls(
    account_response: httpx.Response | None = None,
    account_side_effect: BaseException | None = None,
    pix_key_response: httpx.Response | None = None,
):
    """`account_client` e `pix_key_client` chamam `httpx.get` do MESMO
    modulo `httpx` compartilhado - `patch("app.services.X.httpx.get")` para
    os dois modulos ao mesmo tempo acaba sobrescrevendo um patch com o
    outro (o segundo `with` vence), fazendo a chamada de conta receber a
    resposta da chave PIX ou vice-versa. Um unico patch em `httpx.get` com
    dispatch por URL evita a colisao."""
    if account_response is None and account_side_effect is None:
        account_response = _mock_account_response(200)
    if pix_key_response is None:
        pix_key_response = _mock_pix_key_response(200)

    def _dispatch(url, *args, **kwargs):
        if "/v1/accounts/" in str(url):
            if account_side_effect is not None:
                raise account_side_effect
            return account_response
        if "/v1/pix-keys/lookup" in str(url):
            return pix_key_response
        raise AssertionError(f"chamada upstream inesperada em teste: {url}")

    return patch("httpx.get", side_effect=_dispatch)


def _payload(**overrides) -> dict:
    base = {"account_id": str(uuid.uuid4()), "pix_key_destino": "destino@example.com", "valor": 100.0}
    base.update(overrides)
    return base


def test_post_transaction_happy_path_returns_201() -> None:
    client = TestClient(app)
    account_id = str(uuid.uuid4())

    with _patch_upstream_calls(account_response=_mock_account_response(200, id=account_id)):
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

    with _patch_upstream_calls(
        account_response=_mock_account_response(200, id=account_id),
        pix_key_response=_mock_pix_key_response(200, valor="novo-destino@example.com"),
    ):
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

    with _patch_upstream_calls(account_response=_mock_account_response(200, status="bloqueada")):
        response = client.post("/v1/transactions", json=_payload())

    assert response.status_code == 422
    assert response.json()["error_code"] == "ACCOUNT_NOT_ACTIVE"


def test_post_transaction_conta_inexistente_returns_422() -> None:
    client = TestClient(app)
    not_found = httpx.Response(
        404, json={"error_code": "ACCOUNT_NOT_FOUND", "message": "x", "field": None, "trace_id": "y"}
    )

    with _patch_upstream_calls(account_response=not_found):
        response = client.post("/v1/transactions", json=_payload())

    assert response.status_code == 422
    assert response.json()["error_code"] == "ACCOUNT_NOT_ACTIVE"


def test_post_transaction_pix_key_destino_inexistente_returns_404() -> None:
    client = TestClient(app)
    not_found = httpx.Response(
        404, json={"error_code": "PIX_KEY_NOT_FOUND", "message": "x", "field": None, "trace_id": "y"}
    )

    with _patch_upstream_calls(pix_key_response=not_found):
        response = client.post("/v1/transactions", json=_payload())

    assert response.status_code == 404
    assert response.json()["error_code"] == "PIX_KEY_DESTINO_NOT_FOUND"


def test_post_transaction_pix_key_destino_cancelada_returns_422() -> None:
    client = TestClient(app)

    with _patch_upstream_calls(pix_key_response=_mock_pix_key_response(200, ativa=False)):
        response = client.post("/v1/transactions", json=_payload())

    assert response.status_code == 422
    assert response.json()["error_code"] == "PIX_KEY_DESTINO_INATIVA"


def test_post_transaction_account_service_unavailable_returns_500_without_leaking_details() -> None:
    client = TestClient(app, raise_server_exceptions=False)

    with _patch_upstream_calls(account_side_effect=httpx.ConnectError("connection refused to 10.0.0.1:8002")):
        response = client.post("/v1/transactions", json=_payload())

    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "INTERNAL_ERROR"
    assert "10.0.0.1" not in body["message"]
    assert "httpx" not in body["message"].lower()
