import logging
from unittest.mock import MagicMock

import pytest
from confluent_kafka import KafkaException

from kafka_dlt import (
    DEFAULT_MAX_RETRIES,
    DLT_ERROR_HEADER,
    DLT_FAILED_AT_HEADER,
    DLT_ORIGINAL_TOPIC_HEADER,
    RETRY_COUNT_HEADER,
    dlt_topic_name,
    get_producer,
    get_retry_count,
    handle_processing_failure,
)

_TOPIC = "onboarding.aprovado"


def _headers_dict(headers: list[tuple[str, bytes]]) -> dict[str, bytes]:
    return dict(headers)


def _fake_msg(headers: list[tuple[str, bytes]] | None = None, key: bytes | None = b"k", value: bytes = b"payload") -> MagicMock:
    msg = MagicMock()
    msg.headers.return_value = headers
    msg.key.return_value = key
    msg.value.return_value = value
    return msg


def test_dlt_topic_name_segue_convencao():
    assert dlt_topic_name("onboarding.aprovado") == "onboarding.aprovado.dlt"


def test_get_retry_count_sem_header_retorna_zero():
    assert get_retry_count(None) == 0
    assert get_retry_count([]) == 0


def test_get_retry_count_le_header_existente():
    assert get_retry_count([(RETRY_COUNT_HEADER, b"2")]) == 2


def test_get_retry_count_header_ilegivel_retorna_zero():
    assert get_retry_count([(RETRY_COUNT_HEADER, b"nao-e-um-numero")]) == 0


def test_get_producer_e_singleton_por_bootstrap_servers():
    p1 = get_producer("localhost:9092")
    p2 = get_producer("localhost:9092")
    p3 = get_producer("outrohost:9092")
    assert p1 is p2
    assert p1 is not p3


def test_handle_processing_failure_primeira_falha_reenvia_com_contador_1():
    """Caminho de sucesso apos falha: mensagem sem header ainda (primeira
    falha) deve ser reenviada ao mesmo topico com x-retry-count=1, e o
    offset original deve ser commitado (nunca fica travado)."""
    msg = _fake_msg(headers=[])
    producer = MagicMock()
    producer.flush.return_value = 0
    consumer = MagicMock()
    logger = logging.getLogger("test")

    resultado = handle_processing_failure(
        producer=producer,
        consumer=consumer,
        msg=msg,
        topic=_TOPIC,
        error=RuntimeError("falha transitoria"),
        logger=logger,
        max_retries=3,
    )

    assert resultado == "reenviado"
    produce_kwargs = producer.produce.call_args
    assert produce_kwargs.args[0] == _TOPIC
    headers_sent = _headers_dict(produce_kwargs.kwargs["headers"])
    assert headers_sent[RETRY_COUNT_HEADER] == b"1"
    consumer.commit.assert_called_once_with(message=msg)


def test_handle_processing_failure_atinge_limite_vai_para_dlt_e_avanca_offset():
    """Caminho de sucesso apos N falhas: ao atingir max_retries, a
    mensagem vai para o DLT (nao mais para o topico original), preservando
    payload/headers originais + o erro, e o offset avanca - o consumer
    segue livre para as proximas mensagens."""
    msg = _fake_msg(headers=[(RETRY_COUNT_HEADER, b"2")], key=b"minha-chave", value=b'{"onboarding_id": "x"}')
    producer = MagicMock()
    producer.flush.return_value = 0
    consumer = MagicMock()
    logger = logging.getLogger("test")
    error = ValueError("payload malformado")

    resultado = handle_processing_failure(
        producer=producer,
        consumer=consumer,
        msg=msg,
        topic=_TOPIC,
        error=error,
        logger=logger,
        max_retries=3,
    )

    assert resultado == "dead_letter"
    produce_kwargs = producer.produce.call_args
    assert produce_kwargs.args[0] == "onboarding.aprovado.dlt"
    assert produce_kwargs.kwargs["key"] == b"minha-chave"
    assert produce_kwargs.kwargs["value"] == b'{"onboarding_id": "x"}'

    headers_sent = _headers_dict(produce_kwargs.kwargs["headers"])
    assert headers_sent[RETRY_COUNT_HEADER] == b"3"
    assert headers_sent[DLT_ORIGINAL_TOPIC_HEADER] == _TOPIC.encode("utf-8")
    assert b"ValueError" in headers_sent[DLT_ERROR_HEADER]
    assert b"payload malformado" in headers_sent[DLT_ERROR_HEADER]
    assert DLT_FAILED_AT_HEADER in headers_sent

    consumer.commit.assert_called_once_with(message=msg)


def test_handle_processing_failure_max_retries_zero_forca_dlt_imediato():
    """Falha reconhecidamente permanente (ex. JSON invalido) deve ir direto
    para o DLT mesmo na primeira falha, sem reenviar para o topico
    original - reenviar so adiaria o inevitavel."""
    msg = _fake_msg(headers=[])
    producer = MagicMock()
    producer.flush.return_value = 0
    consumer = MagicMock()
    logger = logging.getLogger("test")

    resultado = handle_processing_failure(
        producer=producer,
        consumer=consumer,
        msg=msg,
        topic=_TOPIC,
        error=ValueError("json invalido"),
        logger=logger,
        max_retries=0,
    )

    assert resultado == "dead_letter"
    assert producer.produce.call_args.args[0] == "onboarding.aprovado.dlt"


def test_handle_processing_failure_usa_default_max_retries_quando_omitido():
    msg = _fake_msg(headers=[(RETRY_COUNT_HEADER, str(DEFAULT_MAX_RETRIES - 1).encode("utf-8"))])
    producer = MagicMock()
    producer.flush.return_value = 0
    consumer = MagicMock()
    logger = logging.getLogger("test")

    resultado = handle_processing_failure(
        producer=producer,
        consumer=consumer,
        msg=msg,
        topic=_TOPIC,
        error=RuntimeError("x"),
        logger=logger,
    )

    assert resultado == "dead_letter"


def test_handle_processing_failure_kafka_exception_no_reenvio_nao_commita():
    """Falha do proprio Kafka (broker inalcancavel, fila cheia) nao e
    poison message - o offset NAO deve avancar, a excecao deve propagar
    para o consumer tentar de novo mais tarde."""
    msg = _fake_msg(headers=[])
    producer = MagicMock()
    producer.produce.side_effect = KafkaException("broker down")
    consumer = MagicMock()
    logger = logging.getLogger("test")

    with pytest.raises(KafkaException):
        handle_processing_failure(
            producer=producer,
            consumer=consumer,
            msg=msg,
            topic=_TOPIC,
            error=RuntimeError("x"),
            logger=logger,
            max_retries=3,
        )

    consumer.commit.assert_not_called()


def test_handle_processing_failure_kafka_exception_no_dlt_nao_commita():
    msg = _fake_msg(headers=[(RETRY_COUNT_HEADER, b"2")])
    producer = MagicMock()
    producer.produce.side_effect = KafkaException("broker down")
    consumer = MagicMock()
    logger = logging.getLogger("test")

    with pytest.raises(KafkaException):
        handle_processing_failure(
            producer=producer,
            consumer=consumer,
            msg=msg,
            topic=_TOPIC,
            error=RuntimeError("x"),
            logger=logger,
            max_retries=3,
        )

    consumer.commit.assert_not_called()
