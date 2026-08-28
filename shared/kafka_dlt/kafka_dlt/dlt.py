"""Tratamento de poison message para consumers Kafka (issue #31,
specs/business/22-poison-message-kafka.md, specs/tech/messaging.md).

Contador de tentativas por mensagem via header Kafka (`x-retry-count`) -
NAO em memoria ou banco. Isso e proposital: como o offset da mensagem
falha nunca avanca sozinho, o processo pode reiniciar quantas vezes for
com a mensagem ainda na mesma posicao - um contador em memoria seria
perdido a cada restart (exatamente o cenario real da issue #31: 18
mensagens cifradas com uma chave ja rotacionada reprocessando para sempre
a cada restart do account-service). Guardar o contador dentro da propria
mensagem Kafka (reenviada para o fim do topico original a cada tentativa
que falha) resolve isso sem precisar de nenhuma tabela/estado adicional.

Apos `max_retries` tentativas, a mensagem (payload e headers originais
intactos, mais o erro) vai para um dead-letter topic dedicado - DLT, nao
DLQ: Kafka trabalha com topicos, nao filas - e so entao o offset original
avanca, liberando o consumer para as proximas mensagens.
"""

import logging
from datetime import datetime, timezone

from confluent_kafka import KafkaException, Message, Producer

RETRY_COUNT_HEADER = "x-retry-count"
DLT_ORIGINAL_TOPIC_HEADER = "x-dlt-original-topic"
DLT_ERROR_HEADER = "x-dlt-error"
DLT_FAILED_AT_HEADER = "x-dlt-failed-at"

DEFAULT_MAX_RETRIES = 3
"""Default razoavel (specs/business/22) - configuravel por servico via
variavel de ambiente propria (ex. KAFKA_MAX_RETRIES), lida pelo
app/core/config.py de cada servico. Este modulo nunca le variavel de
ambiente diretamente, para nao acoplar a lib a nomes de env var
especificos de servico."""

_FLUSH_TIMEOUT_SECONDS = 10.0

_producers: dict[str, Producer] = {}


def dlt_topic_name(topic: str) -> str:
    """Convencao `{topico-original}.dlt` (ex. `onboarding.aprovado.dlt`)."""
    return f"{topic}.dlt"


def get_producer(bootstrap_servers: str) -> Producer:
    """Um Producer por processo por `bootstrap_servers` (mesmo padrao de
    singleton de onboarding-service/app/core/kafka.py), reusado tanto para
    reenviar mensagens em retry quanto para publicar no DLT."""
    if bootstrap_servers not in _producers:
        _producers[bootstrap_servers] = Producer({"bootstrap.servers": bootstrap_servers})
    return _producers[bootstrap_servers]


def get_retry_count(headers: list[tuple[str, bytes]] | None) -> int:
    """Le `x-retry-count` dos headers Kafka da mensagem - 0 se ausente ou
    ilegivel (mensagem nunca antes reenviada)."""
    for key, value in headers or []:
        if key == RETRY_COUNT_HEADER:
            try:
                return int(value.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return 0
    return 0


def _replace_header(
    headers: list[tuple[str, bytes]] | None, key: str, value: bytes
) -> list[tuple[str, bytes]]:
    result = [(k, v) for k, v in (headers or []) if k != key]
    result.append((key, value))
    return result


def _produce_and_flush(producer: Producer, topic: str, msg: Message, headers: list[tuple[str, bytes]]) -> None:
    """Excecao do proprio Kafka (fila cheia, broker inalcancavel) propaga -
    quem chamou `handle_processing_failure` nao deve commitar o offset
    nesse caso: isso NAO e poison message, e uma indisponibilidade de
    infraestrutura, e o consumer reprocessar a mensagem depois (quando o
    Kafka voltar) e o comportamento correto, nao um bug."""
    producer.produce(topic, key=msg.key(), value=msg.value(), headers=headers)
    pending = producer.flush(timeout=_FLUSH_TIMEOUT_SECONDS)
    if pending > 0:
        logging.getLogger(__name__).error(
            "Mensagem nao confirmada como entregue dentro do timeout.",
            extra={"context": {"topic": topic, "mensagens_pendentes": pending}},
        )


def handle_processing_failure(
    *,
    producer: Producer,
    consumer,
    msg: Message,
    topic: str,
    error: BaseException,
    logger: logging.Logger,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> str:
    """Chamado pelo consumer quando o processamento de `msg` falhou. O
    commit do offset acontece SEMPRE aqui dentro (reenvio ou dead-letter,
    nunca os dois, nunca nenhum) - quem chama nao precisa lembrar de
    commitar depois, e o offset da mensagem que falhou nunca fica parado
    esperando reprocessamento indefinido.

    `max_retries=0` forca ida direta ao DLT, sem reenvio - para falhas
    reconhecidamente permanentes (ex. payload que nem chega a ser JSON
    valido: nunca vai suceder em um novo retry, reenviar so adiaria o
    inevitavel).

    Retorna "reenviado" ou "dead_letter"."""
    retry_count = get_retry_count(msg.headers()) + 1

    if retry_count >= max_retries:
        dlt_topic = dlt_topic_name(topic)
        headers = _replace_header(msg.headers(), RETRY_COUNT_HEADER, str(retry_count).encode("utf-8"))
        headers.append((DLT_ORIGINAL_TOPIC_HEADER, topic.encode("utf-8")))
        headers.append((DLT_ERROR_HEADER, f"{type(error).__name__}: {error}".encode("utf-8")))
        headers.append((DLT_FAILED_AT_HEADER, _now_iso().encode("utf-8")))

        try:
            _produce_and_flush(producer, dlt_topic, msg, headers)
        except KafkaException:
            logger.error(
                "Falha ao publicar no dead-letter topic - offset NAO avancado, mensagem sera reprocessada.",
                extra={"context": {"topic": topic, "dlt_topic": dlt_topic, "retry_count": retry_count}},
            )
            raise

        consumer.commit(message=msg)
        logger.error(
            "Limite de tentativas excedido - mensagem movida para dead-letter topic (DLT).",
            extra={
                "context": {
                    "topic": topic,
                    "dlt_topic": dlt_topic,
                    "retry_count": retry_count,
                    "max_retries": max_retries,
                    "error": f"{type(error).__name__}: {error}",
                }
            },
        )
        return "dead_letter"

    headers = _replace_header(msg.headers(), RETRY_COUNT_HEADER, str(retry_count).encode("utf-8"))
    try:
        _produce_and_flush(producer, topic, msg, headers)
    except KafkaException:
        logger.error(
            "Falha ao reenviar mensagem para reprocessamento - offset NAO avancado, sera reentregue.",
            extra={"context": {"topic": topic, "retry_count": retry_count}},
        )
        raise

    consumer.commit(message=msg)
    logger.warning(
        "Falha ao processar mensagem - reenviada para reprocessamento com tentativa incrementada.",
        extra={
            "context": {
                "topic": topic,
                "retry_count": retry_count,
                "max_retries": max_retries,
                "error": f"{type(error).__name__}: {error}",
            }
        },
    )
    return "reenviado"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
