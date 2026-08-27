import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from test_safety import require_disposable_database

from app.core.config import get_settings
from app.main import app

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not settings.database_url,
    reason="DATABASE_URL nao configurada - teste de contrato de pix-keys requer banco real.",
)


@pytest.fixture(autouse=True)
def _clean_pix_keys_table():
    require_disposable_database(settings.database_url)
    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE pix_keys"))
    yield
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE pix_keys"))


def _payload(**overrides) -> dict:
    base = {"account_id": str(uuid.uuid4()), "tipo": "email", "valor": "user@example.com"}
    base.update(overrides)
    return base


def test_post_pix_key_happy_path_returns_201() -> None:
    client = TestClient(app)

    response = client.post("/v1/pix-keys", json=_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["tipo"] == "email"
    assert body["valor"] == "user@example.com"
    assert "id" in body
    assert "created_at" in body


@pytest.mark.parametrize(
    ("tipo", "valor"),
    [
        ("cpf", "12345678901"),
        ("email", "user@example.com"),
        ("telefone", "11999999999"),
        ("aleatoria", "qualquer-valor-aceito"),
    ],
)
def test_post_pix_key_accepts_all_tipos_com_valor_compativel(tipo: str, valor: str) -> None:
    client = TestClient(app)

    response = client.post("/v1/pix-keys", json=_payload(tipo=tipo, valor=valor))

    assert response.status_code == 201
    assert response.json()["tipo"] == tipo


def test_post_pix_key_tipo_fora_do_enum_returns_400() -> None:
    client = TestClient(app)

    response = client.post("/v1/pix-keys", json=_payload(tipo="invalido"))

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["field"] == "tipo"


@pytest.mark.parametrize(
    ("tipo", "valor"),
    [
        ("cpf", "123"),
        ("email", "nao-e-email"),
        ("telefone", "abc"),
    ],
)
def test_post_pix_key_valor_incompativel_com_tipo_returns_400(tipo: str, valor: str) -> None:
    client = TestClient(app)

    response = client.post("/v1/pix-keys", json=_payload(tipo=tipo, valor=valor))

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "VALIDATION_ERROR"
    assert body["field"] == "valor"


def test_post_pix_key_valor_ja_registrado_returns_409() -> None:
    client = TestClient(app)
    client.post("/v1/pix-keys", json=_payload(valor="duplicado@example.com"))

    response = client.post(
        "/v1/pix-keys", json=_payload(account_id=str(uuid.uuid4()), valor="duplicado@example.com")
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "PIX_KEY_ALREADY_REGISTERED"


def test_post_pix_key_valor_reaproveitado_apos_delete_returns_201() -> None:
    client = TestClient(app)
    created = client.post("/v1/pix-keys", json=_payload(valor="reuso@example.com"))
    client.delete(f"/v1/pix-keys/{created.json()['id']}")

    response = client.post("/v1/pix-keys", json=_payload(valor="reuso@example.com"))

    assert response.status_code == 201


def test_delete_pix_key_happy_path_returns_204() -> None:
    client = TestClient(app)
    created = client.post("/v1/pix-keys", json=_payload())

    response = client.delete(f"/v1/pix-keys/{created.json()['id']}")

    assert response.status_code == 204


def test_delete_pix_key_ja_deletado_returns_404() -> None:
    client = TestClient(app)
    created = client.post("/v1/pix-keys", json=_payload())
    client.delete(f"/v1/pix-keys/{created.json()['id']}")

    response = client.delete(f"/v1/pix-keys/{created.json()['id']}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "PIX_KEY_NOT_FOUND"


def test_delete_pix_key_inexistente_returns_404() -> None:
    client = TestClient(app)

    response = client.delete(f"/v1/pix-keys/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "PIX_KEY_NOT_FOUND"


def test_get_pix_key_lookup_chave_ativa_returns_200_ativa_true() -> None:
    client = TestClient(app)
    created = client.post("/v1/pix-keys", json=_payload(valor="lookup-ativa@example.com"))

    response = client.get("/v1/pix-keys/lookup", params={"valor": "lookup-ativa@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created.json()["id"]
    assert body["ativa"] is True


def test_get_pix_key_lookup_chave_cancelada_returns_200_ativa_false() -> None:
    client = TestClient(app)
    created = client.post("/v1/pix-keys", json=_payload(valor="lookup-cancelada@example.com"))
    client.delete(f"/v1/pix-keys/{created.json()['id']}")

    response = client.get("/v1/pix-keys/lookup", params={"valor": "lookup-cancelada@example.com"})

    assert response.status_code == 200
    assert response.json()["ativa"] is False


def test_get_pix_key_lookup_chave_inexistente_returns_404() -> None:
    client = TestClient(app)

    response = client.get("/v1/pix-keys/lookup", params={"valor": "nunca-existiu@example.com"})

    assert response.status_code == 404
    assert response.json()["error_code"] == "PIX_KEY_NOT_FOUND"
