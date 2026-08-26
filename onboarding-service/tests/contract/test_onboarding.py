import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.main import app

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.database_url,
    reason="DATABASE_URL nao configurada - teste de contrato do onboarding requer banco real.",
)


@pytest.fixture(autouse=True)
def _clean_onboardings_table():
    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE onboardings"))
    yield
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE onboardings"))


def _valid_payload(cpf: str = "12345678901") -> dict:
    return {
        "cpf": cpf,
        "nome": "Maria da Silva",
        "data_nascimento": "1990-05-20",
        "email": "maria@example.com",
        "telefone": "11999999999",
        "documento_tipo": "rg",
        "documento_numero": "1234567",
        "dispositivo_id": "device-123",
        "ip_origem": "203.0.113.10",
    }


def test_post_onboarding_happy_path_returns_201() -> None:
    client = TestClient(app)

    response = client.post("/v1/onboarding", json=_valid_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "em_analise"
    uuid.UUID(body["id"])
    assert "created_at" in body


def test_post_onboarding_missing_field_returns_400() -> None:
    client = TestClient(app)
    payload = _valid_payload()
    del payload["nome"]

    response = client.post("/v1/onboarding", json=payload)

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["field"] == "nome"


def test_post_onboarding_invalid_cpf_format_returns_400() -> None:
    client = TestClient(app)
    payload = _valid_payload(cpf="abc123")

    response = client.post("/v1/onboarding", json=payload)

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["field"] == "cpf"


def test_post_onboarding_invalid_email_format_returns_400() -> None:
    client = TestClient(app)
    payload = _valid_payload()
    payload["email"] = "nao-e-um-email"

    response = client.post("/v1/onboarding", json=payload)

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["field"] == "email"


def test_post_onboarding_duplicate_cpf_returns_409() -> None:
    client = TestClient(app)
    payload = _valid_payload(cpf="98765432100")
    client.post("/v1/onboarding", json=payload)

    response = client.post("/v1/onboarding", json=payload)

    assert response.status_code == 409
    body = response.json()
    assert body["error_code"] == "CPF_ALREADY_REGISTERED"
    assert body["field"] == "cpf"


def test_get_onboarding_happy_path_returns_200_with_empty_risco() -> None:
    client = TestClient(app)
    created = client.post("/v1/onboarding", json=_valid_payload(cpf="11122233344")).json()

    response = client.get(f"/v1/onboarding/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"]
    assert body["status"] == "em_analise"
    assert body["risco_cadastro"]["score"] is None
    assert body["risco_cadastro"]["sinais"] == []


def test_get_onboarding_not_found_returns_404() -> None:
    client = TestClient(app)

    response = client.get(f"/v1/onboarding/{uuid.uuid4()}")

    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "ONBOARDING_NOT_FOUND"
