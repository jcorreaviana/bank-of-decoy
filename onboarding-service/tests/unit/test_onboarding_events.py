import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.services.onboarding_events import publish_onboarding_classified


class _FakeDbCpf:
    """Duplo de Session: so precisa responder a
    `onboarding_repository.get_raw_cpf_ciphertext` (SELECT bruto), usado
    apenas quando `status == aprovado`."""

    def __init__(self, ciphertext: str | None) -> None:
        self._ciphertext = ciphertext

    def execute(self, *_args, **_kwargs):
        ciphertext = self._ciphertext

        class _Result:
            def first(self_inner):
                return (ciphertext,) if ciphertext is not None else None

        return _Result()


def _onboarding(**overrides) -> SimpleNamespace:
    base = dict(
        id=uuid.uuid4(),
        status="aprovado",
        motivo_reprovacao=None,
        risco_score=12.5,
        risco_sinais=["dados_inconsistentes"],
        updated_at=datetime(2026, 1, 1, 12, 0, 0, 123000, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_publish_onboarding_classified_aprovado_publica_um_topico_com_cpf_cifrado() -> None:
    onboarding = _onboarding(status="aprovado")
    db = _FakeDbCpf("ciphertext-fake")

    with patch("app.services.onboarding_events.publish_events") as mock_publish:
        publish_onboarding_classified(db, onboarding)

    mock_publish.assert_called_once()
    (eventos,) = mock_publish.call_args.args
    assert len(eventos) == 1
    topic, envelope, key = eventos[0]
    assert topic == "onboarding.aprovado"
    assert key == str(onboarding.id)
    assert envelope["event_type"] == "onboarding.aprovado"
    assert uuid.UUID(envelope["event_id"])  # formato valido
    assert envelope["occurred_at"] == "2026-01-01T12:00:00.123Z"
    assert envelope["payload"]["onboarding_id"] == str(onboarding.id)
    assert envelope["payload"]["cpf"] == "ciphertext-fake"
    assert envelope["payload"]["risco_score"] == 12.5
    assert envelope["payload"]["risco_sinais"] == ["dados_inconsistentes"]
    assert "motivo_reprovacao" not in envelope["payload"]
    assert "nome" not in envelope["payload"]
    assert "email" not in envelope["payload"]
    assert "telefone" not in envelope["payload"]


def test_publish_onboarding_classified_reprovado_qualidade_publica_dois_topicos_mesmo_evento_num_unico_flush() -> None:
    onboarding = _onboarding(status="reprovado_qualidade", motivo_reprovacao="documento_formato_invalido")
    db = _FakeDbCpf(None)

    with patch("app.services.onboarding_events.publish_events") as mock_publish:
        publish_onboarding_classified(db, onboarding)

    mock_publish.assert_called_once()  # issue #69: um unico flush para os dois topicos
    (eventos,) = mock_publish.call_args.args
    topicos = [topic for topic, _envelope, _key in eventos]
    assert topicos == ["onboarding.reprovado_qualidade", "onboarding.revisao_qualidade"]

    event_ids = {envelope["event_id"] for _topic, envelope, _key in eventos}
    assert len(event_ids) == 1  # mesmo fato de negocio, dois topicos

    payload = eventos[0][1]["payload"]
    assert payload["motivo_reprovacao"] == "documento_formato_invalido"
    assert "cpf" not in payload


def test_publish_onboarding_classified_reprovado_fraude_publica_fila_compliance() -> None:
    onboarding = _onboarding(status="reprovado_fraude", motivo_reprovacao="pep_detectado")
    db = _FakeDbCpf(None)

    with patch("app.services.onboarding_events.publish_events") as mock_publish:
        publish_onboarding_classified(db, onboarding)

    (eventos,) = mock_publish.call_args.args
    topicos = [topic for topic, _envelope, _key in eventos]
    assert topicos == ["onboarding.reprovado_fraude", "onboarding.revisao_compliance"]


def test_publish_onboarding_classified_em_analise_nao_publica_nada() -> None:
    onboarding = _onboarding(status="em_analise")
    db = _FakeDbCpf(None)

    with patch("app.services.onboarding_events.publish_events") as mock_publish:
        publish_onboarding_classified(db, onboarding)

    mock_publish.assert_not_called()
