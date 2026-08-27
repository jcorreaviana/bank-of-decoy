import os
import uuid
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.crypto import encrypt_value
from app.main import app

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.database_url or not os.environ.get("CPF_ENCRYPTION_KEY"),
    reason="DATABASE_URL/CPF_ENCRYPTION_KEY nao configuradas - teste de contrato de accounts requer banco real.",
)


@pytest.fixture(autouse=True)
def _clean_accounts_table():
    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE accounts"))
    yield
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE accounts"))


def _mock_onboarding_response(status_code: int, **overrides) -> httpx.Response:
    payload = {
        "id": str(uuid.uuid4()),
        "cpf": encrypt_value("12345678901"),
        "status": "aprovado",
        "risco_cadastro": {"score": 12.5, "sinais": ["dados_inconsistentes"]},
        "created_at": "2026-01-01T00:00:00.000Z",
    }
    payload.update(overrides)
    return httpx.Response(status_code, json=payload)


def _patch_onboarding_get(response: httpx.Response | None = None, side_effect=None):
    target = "app.services.onboarding_internal_client.httpx.get"
    if side_effect is not None:
        return patch(target, side_effect=side_effect)
    return patch(target, return_value=response)


def test_post_account_happy_path_inherits_risco() -> None:
    client = TestClient(app)
    onboarding_id = str(uuid.uuid4())

    with _patch_onboarding_get(_mock_onboarding_response(200, id=onboarding_id)):
        response = client.post("/v1/accounts", json={"onboarding_id": onboarding_id, "tipo_conta": "corrente"})

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ativa"

    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        row = connection.execute(
            text("SELECT risco_score, risco_sinais, tipo_conta, cpf FROM accounts WHERE id = :id"),
            {"id": body["id"]},
        ).one()
    assert float(row.risco_score) == 12.5
    assert row.risco_sinais == ["dados_inconsistentes"]
    assert row.tipo_conta == "corrente"
    assert row.cpf != "12345678901"  # criptografado em repouso (issue #10)


def test_post_account_missing_tipo_conta_returns_400() -> None:
    client = TestClient(app)

    response = client.post("/v1/accounts", json={"onboarding_id": str(uuid.uuid4())})

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["field"] == "tipo_conta"


def test_post_account_invalid_tipo_conta_returns_400() -> None:
    client = TestClient(app)

    response = client.post("/v1/accounts", json={"onboarding_id": str(uuid.uuid4()), "tipo_conta": "invalido"})

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["field"] == "tipo_conta"


def test_post_account_onboarding_not_found_returns_404() -> None:
    client = TestClient(app)
    not_found = httpx.Response(
        404, json={"error_code": "ONBOARDING_NOT_FOUND", "message": "x", "field": None, "trace_id": "y"}
    )

    with _patch_onboarding_get(not_found):
        response = client.post("/v1/accounts", json={"onboarding_id": str(uuid.uuid4()), "tipo_conta": "corrente"})

    assert response.status_code == 404
    assert response.json()["error_code"] == "ONBOARDING_NOT_FOUND"


@pytest.mark.parametrize("status_value", ["em_analise", "reprovado_qualidade", "reprovado_fraude"])
def test_post_account_onboarding_not_approved_returns_422(status_value: str) -> None:
    client = TestClient(app)

    with _patch_onboarding_get(_mock_onboarding_response(200, status=status_value)):
        response = client.post("/v1/accounts", json={"onboarding_id": str(uuid.uuid4()), "tipo_conta": "corrente"})

    assert response.status_code == 422
    assert response.json()["error_code"] == "ONBOARDING_NOT_APPROVED"


def test_post_account_duplicate_returns_409() -> None:
    client = TestClient(app)
    onboarding_id = str(uuid.uuid4())

    with _patch_onboarding_get(_mock_onboarding_response(200, id=onboarding_id)):
        first = client.post("/v1/accounts", json={"onboarding_id": onboarding_id, "tipo_conta": "corrente"})
        assert first.status_code == 201

        second = client.post("/v1/accounts", json={"onboarding_id": onboarding_id, "tipo_conta": "poupanca"})

    assert second.status_code == 409
    assert second.json()["error_code"] == "ACCOUNT_ALREADY_EXISTS"


def test_post_account_onboarding_service_unexpected_error_returns_500() -> None:
    client = TestClient(app, raise_server_exceptions=False)
    server_error = httpx.Response(
        500, json={"error_code": "INTERNAL_ERROR", "message": "x", "field": None, "trace_id": "y"}
    )

    with _patch_onboarding_get(server_error):
        response = client.post("/v1/accounts", json={"onboarding_id": str(uuid.uuid4()), "tipo_conta": "corrente"})

    assert response.status_code == 500
    assert response.json()["error_code"] == "INTERNAL_ERROR"


def test_get_account_happy_path_returns_status() -> None:
    client = TestClient(app)
    onboarding_id = str(uuid.uuid4())

    with _patch_onboarding_get(_mock_onboarding_response(200, id=onboarding_id)):
        created = client.post("/v1/accounts", json={"onboarding_id": onboarding_id, "tipo_conta": "corrente"})

    response = client.get(f"/v1/accounts/{created.json()['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ativa"
    assert body["tipo_conta"] == "corrente"
    assert "cpf" not in body


def test_get_account_not_found_returns_404() -> None:
    client = TestClient(app)

    response = client.get(f"/v1/accounts/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "ACCOUNT_NOT_FOUND"


def test_post_account_onboarding_service_unavailable_returns_500_without_leaking_details() -> None:
    # raise_server_exceptions=False: queremos a resposta 500 que o handler
    # generico ja construiu, nao a excecao re-levantada pelo TestClient
    # (comportamento padrao dele para depuracao) - em producao real
    # (uvicorn) o cliente sempre recebe a resposta HTTP limpa.
    client = TestClient(app, raise_server_exceptions=False)

    with _patch_onboarding_get(side_effect=httpx.ConnectError("connection refused to 10.0.0.1:8001")):
        response = client.post("/v1/accounts", json={"onboarding_id": str(uuid.uuid4()), "tipo_conta": "corrente"})

    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "INTERNAL_ERROR"
    assert "10.0.0.1" not in body["message"]
    assert "httpx" not in body["message"].lower()
    assert "connection" not in body["message"].lower()
