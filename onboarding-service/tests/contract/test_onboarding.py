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


def _valid_payload(cpf: str = "12345678901", **overrides) -> dict:
    payload = {
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
    payload.update(overrides)
    return payload


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


def test_get_onboarding_not_found_returns_404() -> None:
    client = TestClient(app)

    response = client.get(f"/v1/onboarding/{uuid.uuid4()}")

    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "ONBOARDING_NOT_FOUND"


# --- classificacao de risco (issue #4): a classificacao roda de forma
# sincrona logo apos o POST, entao por essas o GET ja reflete o resultado. ---


def test_get_onboarding_aprovado_sem_sinais_registra_score_zero() -> None:
    client = TestClient(app)
    created = client.post("/v1/onboarding", json=_valid_payload(cpf="11122233344")).json()

    response = client.get(f"/v1/onboarding/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "aprovado"
    assert body["risco_cadastro"]["score"] == 0.0
    assert body["risco_cadastro"]["sinais"] == []


def test_get_onboarding_aprovado_com_sinal_leve_mantem_score_registrado() -> None:
    client = TestClient(app)
    # nome com digito dispara so dados_inconsistentes (25 pontos) - abaixo do limiar de 50
    created = client.post(
        "/v1/onboarding", json=_valid_payload(cpf="55566677788", nome="Fulano2")
    ).json()

    response = client.get(f"/v1/onboarding/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "aprovado"
    assert body["risco_cadastro"]["score"] == 25.0
    assert body["risco_cadastro"]["sinais"] == ["dados_inconsistentes"]


def test_get_onboarding_reprovado_qualidade_com_multiplos_sinais() -> None:
    client = TestClient(app)
    # documento_formato_invalido (30) + dados_inconsistentes (25) = 55 >= 50
    created = client.post(
        "/v1/onboarding",
        json=_valid_payload(cpf="99988877766", documento_numero="!", nome="Fulano2"),
    ).json()

    response = client.get(f"/v1/onboarding/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "reprovado_qualidade"
    assert body["risco_cadastro"]["score"] == 55.0
    assert set(body["risco_cadastro"]["sinais"]) == {"documento_formato_invalido", "dados_inconsistentes"}


def test_get_onboarding_reprovado_fraude_por_pep() -> None:
    client = TestClient(app)
    created = client.post("/v1/onboarding", json=_valid_payload(cpf="11111111111")).json()

    response = client.get(f"/v1/onboarding/{created['id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "reprovado_fraude"
    assert body["risco_cadastro"]["score"] == 100.0
    assert body["risco_cadastro"]["sinais"] == ["pep_detectado"]


def test_fraude_sobrepoe_contagem_de_sinais_de_qualidade() -> None:
    client = TestClient(app)
    # payload dispara varios sinais de qualidade (documento invalido + dados
    # inconsistentes, soma 55) E um sinal de fraude (PEP) ao mesmo tempo.
    created = client.post(
        "/v1/onboarding",
        json=_valid_payload(cpf="11111111111", documento_numero="!", nome="Fulano2"),
    ).json()

    response = client.get(f"/v1/onboarding/{created['id']}")

    body = response.json()
    assert body["status"] == "reprovado_fraude"
    assert body["risco_cadastro"]["score"] == 100.0
    assert body["risco_cadastro"]["sinais"] == ["pep_detectado"]


def test_documento_reciclado_reprova_segundo_onboarding_com_mesmo_documento() -> None:
    client = TestClient(app)
    primeiro = client.post(
        "/v1/onboarding",
        json=_valid_payload(
            cpf="10101010101", documento_numero="DOC-RECICLADO", ip_origem="1.1.1.1", dispositivo_id="dev-a"
        ),
    ).json()
    assert client.get(f"/v1/onboarding/{primeiro['id']}").json()["status"] == "aprovado"

    segundo = client.post(
        "/v1/onboarding",
        json=_valid_payload(
            cpf="20202020202", documento_numero="DOC-RECICLADO", ip_origem="2.2.2.2", dispositivo_id="dev-b"
        ),
    ).json()

    response = client.get(f"/v1/onboarding/{segundo['id']}")
    body = response.json()
    assert body["status"] == "reprovado_fraude"
    assert body["risco_cadastro"]["sinais"] == ["documento_reciclado"]


def test_padrao_mula_reprova_segundo_onboarding_com_mesmo_ip() -> None:
    client = TestClient(app)
    primeiro = client.post(
        "/v1/onboarding",
        json=_valid_payload(
            cpf="30303030303", documento_numero="DOC-MULA-A", ip_origem="9.9.9.9", dispositivo_id="dev-mula-a"
        ),
    ).json()
    assert client.get(f"/v1/onboarding/{primeiro['id']}").json()["status"] == "aprovado"

    segundo = client.post(
        "/v1/onboarding",
        json=_valid_payload(
            cpf="40404040404", documento_numero="DOC-MULA-B", ip_origem="9.9.9.9", dispositivo_id="dev-mula-b"
        ),
    ).json()

    response = client.get(f"/v1/onboarding/{segundo['id']}")
    body = response.json()
    assert body["status"] == "reprovado_fraude"
    assert body["risco_cadastro"]["sinais"] == ["padrao_mula"]


def test_motivo_reprovacao_persistido_no_banco_reflete_o_sinal_disparado() -> None:
    client = TestClient(app)
    created = client.post("/v1/onboarding", json=_valid_payload(cpf="11111111111")).json()

    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        motivo = connection.execute(
            text("SELECT motivo_reprovacao FROM onboardings WHERE id = :id"), {"id": created["id"]}
        ).scalar_one()

    assert motivo == "pep_detectado"
