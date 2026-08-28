import os
import uuid
from unittest.mock import Mock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from test_safety import require_disposable_database

from app.core.config import get_settings
from app.main import app
from app.services import pix_key_service

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


def _mock_account_response(status_code: int, **overrides) -> httpx.Response:
    payload = {
        "id": str(uuid.uuid4()),
        "status": "ativa",
        "tipo_conta": "corrente",
        "created_at": "2026-01-01T00:00:00.000Z",
    }
    payload.update(overrides)
    return httpx.Response(status_code, json=payload)


def _patch_account_service(response: httpx.Response | None = None, side_effect: BaseException | None = None):
    """Faz o patch diretamente no `_client` (httpx.Client persistente,
    ver comentario em app/services/pix_key_service.py) usado por
    `_fetch_account`, nao na classe `httpx.Client` inteira - patchear a
    classe intercetaria tambem as chamadas do proprio `TestClient` (que e
    subclasse de `httpx.Client`) contra a app sob teste."""
    if response is None and side_effect is None:
        response = _mock_account_response(200)

    def _dispatch_get(url, *args, **kwargs):
        if "/v1/accounts/" in str(url):
            if side_effect is not None:
                raise side_effect
            return response
        raise AssertionError(f"chamada GET upstream inesperada em teste: {url}")

    return patch.object(pix_key_service, "_client", spec=httpx.Client, get=Mock(side_effect=_dispatch_get))


def _payload(**overrides) -> dict:
    base = {"account_id": str(uuid.uuid4()), "tipo": "email", "valor": "user@example.com"}
    base.update(overrides)
    return base


def test_post_pix_key_happy_path_returns_201() -> None:
    client = TestClient(app)

    with _patch_account_service():
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

    with _patch_account_service():
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


def test_post_pix_key_conta_inexistente_returns_404() -> None:
    """specs/business/06-pixkey-transaction-crud.md nao documentava esse
    caso, mas docs/escopo-arquitetura.md (fonte de verdade) sempre previu
    404 para conta inexistente em POST /v1/pix-keys - lacuna corrigida na
    issue #35 (tests/scenarios/pix_key_conta_inexistente.md)."""
    client = TestClient(app)
    not_found = httpx.Response(
        404, json={"error_code": "ACCOUNT_NOT_FOUND", "message": "x", "field": None, "trace_id": "y"}
    )

    with _patch_account_service(response=not_found):
        response = client.post("/v1/pix-keys", json=_payload())

    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "ACCOUNT_NOT_FOUND"
    assert body["field"] == "account_id"


def test_post_pix_key_account_service_unavailable_returns_500_without_leaking_details() -> None:
    client = TestClient(app, raise_server_exceptions=False)

    with _patch_account_service(side_effect=httpx.ConnectError("connection refused to 10.0.0.1:8002")):
        response = client.post("/v1/pix-keys", json=_payload())

    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "INTERNAL_ERROR"
    assert "10.0.0.1" not in body["message"]
    assert "httpx" not in body["message"].lower()


def test_post_pix_key_valor_ja_registrado_returns_409() -> None:
    client = TestClient(app)
    with _patch_account_service():
        client.post("/v1/pix-keys", json=_payload(valor="duplicado@example.com"))

        response = client.post(
            "/v1/pix-keys", json=_payload(account_id=str(uuid.uuid4()), valor="duplicado@example.com")
        )

    assert response.status_code == 409
    assert response.json()["error_code"] == "PIX_KEY_ALREADY_REGISTERED"


def test_post_pix_key_valor_reaproveitado_apos_delete_returns_201() -> None:
    client = TestClient(app)
    with _patch_account_service():
        created = client.post("/v1/pix-keys", json=_payload(valor="reuso@example.com"))
        client.delete(f"/v1/pix-keys/{created.json()['id']}")

        response = client.post("/v1/pix-keys", json=_payload(valor="reuso@example.com"))

    assert response.status_code == 201


def test_delete_pix_key_happy_path_returns_204() -> None:
    client = TestClient(app)
    with _patch_account_service():
        created = client.post("/v1/pix-keys", json=_payload())

    response = client.delete(f"/v1/pix-keys/{created.json()['id']}")

    assert response.status_code == 204


def test_delete_pix_key_ja_deletado_returns_404() -> None:
    client = TestClient(app)
    with _patch_account_service():
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
    with _patch_account_service():
        created = client.post("/v1/pix-keys", json=_payload(valor="lookup-ativa@example.com"))

    response = client.get("/v1/pix-keys/lookup", params={"valor": "lookup-ativa@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created.json()["id"]
    assert body["ativa"] is True


def test_get_pix_key_lookup_chave_cancelada_returns_200_ativa_false() -> None:
    client = TestClient(app)
    with _patch_account_service():
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
