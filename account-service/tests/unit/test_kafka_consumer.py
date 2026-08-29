from unittest.mock import MagicMock, patch

import pytest
from chaos import kafka_chaos
from chaos.runtime_config import clear_runtime_override, set_runtime_override
from confluent_kafka import KafkaException

from app.core import kafka_consumer


@pytest.fixture(autouse=True)
def _clean_chaos_runtime_override():
    clear_runtime_override()
    yield
    clear_runtime_override()


def _msg(value: bytes = b'{"event_id": "e1"}') -> MagicMock:
    msg = MagicMock()
    msg.value.return_value = value
    msg.headers.return_value = []
    msg.key.return_value = b"k"
    return msg


def test_handle_message_sucesso_na_primeira_tentativa_nao_toca_no_dlt():
    """Caminho de sucesso normal: mensagem processa na primeira tentativa
    - so commita o offset diretamente, nunca passa pelo kafka_dlt."""
    consumer = MagicMock()
    msg = _msg()
    db = MagicMock()

    with (
        patch("app.core.kafka_consumer.SessionLocal", return_value=db),
        patch(
            "app.core.kafka_consumer.process_onboarding_aprovado_envelope", return_value="conta_criada"
        ) as mock_process,
        patch("app.core.kafka_consumer.handle_processing_failure") as mock_dlt,
        patch("app.core.kafka_consumer.get_producer"),
    ):
        kafka_consumer._handle_message(consumer, msg)

    mock_process.assert_called_once()
    consumer.commit.assert_called_once_with(message=msg)
    mock_dlt.assert_not_called()
    db.rollback.assert_not_called()


def test_handle_message_payload_invalido_vai_direto_para_dlt_sem_retry():
    """Payload que nem chega a ser JSON valido e uma falha permanente -
    max_retries=0 forca ida direta ao DLT, sem reenviar para retry."""
    consumer = MagicMock()
    msg = _msg(value=b"isto nao e json")
    producer = MagicMock()

    with (
        patch("app.core.kafka_consumer.get_producer", return_value=producer) as mock_get_producer,
        patch("app.core.kafka_consumer.handle_processing_failure") as mock_dlt,
    ):
        kafka_consumer._handle_message(consumer, msg)

    mock_get_producer.assert_called_once()
    mock_dlt.assert_called_once()
    kwargs = mock_dlt.call_args.kwargs
    assert kwargs["topic"] == kafka_consumer.TOPIC
    assert kwargs["max_retries"] == 0
    assert isinstance(kwargs["error"], ValueError)
    assert kwargs["consumer"] is consumer
    assert kwargs["msg"] is msg


def test_handle_message_falha_no_processamento_aciona_kafka_dlt_com_max_retries_configurado():
    """Falha ao processar o envelope (ex. InvalidToken do incidente real)
    aciona o kafka_dlt com o limite configurado por env var, nunca mais
    fica sem commitar/reenviar para sempre."""
    consumer = MagicMock()
    msg = _msg()
    db = MagicMock()
    erro = RuntimeError("falha simulada de processamento")

    settings = MagicMock(kafka_bootstrap_servers="localhost:29092", kafka_max_retries=5)

    with (
        patch("app.core.kafka_consumer.get_settings", return_value=settings),
        patch("app.core.kafka_consumer.SessionLocal", return_value=db),
        patch("app.core.kafka_consumer.process_onboarding_aprovado_envelope", side_effect=erro),
        patch("app.core.kafka_consumer.get_producer") as mock_get_producer,
        patch("app.core.kafka_consumer.handle_processing_failure") as mock_dlt,
    ):
        kafka_consumer._handle_message(consumer, msg)

    db.rollback.assert_called_once()
    mock_get_producer.assert_called_once_with("localhost:29092")
    mock_dlt.assert_called_once()
    kwargs = mock_dlt.call_args.kwargs
    assert kwargs["max_retries"] == 5
    assert kwargs["error"] is erro
    consumer.commit.assert_not_called()  # commit e responsabilidade do kafka_dlt, nao daqui


def test_handle_message_sem_database_url_nao_aciona_dlt_nem_commita():
    """Config ausente nao e poison message (e' operavel, resolve quando o
    banco for configurado) - continua sem passar pelo kafka_dlt."""
    consumer = MagicMock()
    msg = _msg()

    with (
        patch("app.core.kafka_consumer.SessionLocal", None),
        patch("app.core.kafka_consumer.handle_processing_failure") as mock_dlt,
    ):
        kafka_consumer._handle_message(consumer, msg)

    mock_dlt.assert_not_called()
    consumer.commit.assert_not_called()


def test_run_consumer_applies_growing_kafka_lag_delay_without_stopping_consumption(monkeypatch):
    """kafka_lag real (issue #52, specs/business/24-camada-caos-avancada.md)
    - a decisao de caos (chaos/kafka_chaos.py) NAO e mockada aqui, so o
    Kafka em si (Consumer/_handle_message, mesmo limite dos outros testes
    deste arquivo) e time.sleep (para o teste nao esperar de verdade).
    Confirma que o consumer real continua consumindo (chama
    _handle_message a cada mensagem) e que o atraso cresce mensagem a
    mensagem, sem travar."""
    set_runtime_override(enabled=True, failure_rate=1.0, failure_types=["kafka_lag"], duration_seconds=None)
    monkeypatch.setattr(kafka_chaos.random, "random", lambda: 0.0)

    stop_event = MagicMock()
    stop_event.is_set.side_effect = [False, False, False, True]

    consumer_instance = MagicMock()
    msg = _msg()
    msg.error.return_value = None
    consumer_instance.poll.return_value = msg

    sleep_calls: list[float] = []
    monkeypatch.setattr(kafka_consumer.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    with (
        patch("app.core.kafka_consumer.Consumer", return_value=consumer_instance),
        patch("app.core.kafka_consumer._handle_message") as mock_handle,
    ):
        kafka_consumer.run_onboarding_aprovado_consumer(stop_event)

    assert mock_handle.call_count == 3
    assert len(sleep_calls) == 3
    assert sleep_calls[0] < sleep_calls[1] < sleep_calls[2]


def test_run_consumer_does_not_delay_when_kafka_lag_not_active(monkeypatch):
    stop_event = MagicMock()
    stop_event.is_set.side_effect = [False, True]

    consumer_instance = MagicMock()
    msg = _msg()
    msg.error.return_value = None
    consumer_instance.poll.return_value = msg

    sleep_calls: list[float] = []
    monkeypatch.setattr(kafka_consumer.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    with (
        patch("app.core.kafka_consumer.Consumer", return_value=consumer_instance),
        patch("app.core.kafka_consumer._handle_message") as mock_handle,
    ):
        kafka_consumer.run_onboarding_aprovado_consumer(stop_event)

    mock_handle.assert_called_once()
    assert sleep_calls == []


def test_run_consumer_sobrevive_a_kafka_exception_do_dlt_sem_matar_a_thread():
    """Regressao critica: se kafka_dlt propagar KafkaException (broker
    inalcancavel ao reenviar/publicar no DLT), o loop de polling nao pode
    morrer em silencio - precisa logar CRITICAL e seguir tentando."""
    stop_event = MagicMock()
    stop_event.is_set.side_effect = [False, True]  # um ciclo, depois para

    consumer_instance = MagicMock()
    msg = _msg()
    msg.error.return_value = None
    consumer_instance.poll.return_value = msg

    with (
        patch("app.core.kafka_consumer.Consumer", return_value=consumer_instance),
        patch("app.core.kafka_consumer._handle_message", side_effect=KafkaException("broker down")),
    ):
        kafka_consumer.run_onboarding_aprovado_consumer(stop_event)

    consumer_instance.close.assert_called_once()
