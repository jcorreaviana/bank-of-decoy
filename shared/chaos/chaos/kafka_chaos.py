"""Decisao de injecao de caos para os dois pontos de integracao Kafka -
issue #52, specs/business/24-camada-caos-avancada.md.

kafka_lag e kafka_delay nao passam pelo ChaosMiddleware (que so
intercepta requisicoes HTTP, via ASGI) - o producer (onboarding-service,
app/core/kafka.py::publish_event) e o consumer (account-service,
app/core/kafka_consumer.py) consultam as funcoes abaixo diretamente,
antes de publicar/processar cada mensagem. Reaproveitam a mesma decisao
probabilistica do middleware (enabled + tipo na lista ativa + sorteio
por failure_rate) - so que aplicada por mensagem/publicacao, nao por
request HTTP.
"""

import random

from chaos.middleware import _load_config
from chaos.runtime_config import get_active_type_params, record_kafka_lag_message


def maybe_kafka_lag_delay_seconds() -> float | None:
    """Chamada pelo consumer antes de processar cada mensagem. Retorna o
    atraso (segundos) a aplicar desta vez, ou None se kafka_lag nao
    estiver ativo/sorteado agora - nunca para de consumir, so atrasa.

    O atraso cresce a cada mensagem que o sorteio afeta (contador em
    chaos/runtime_config.py, resetado a cada POST /internal/chaos/config),
    ate o teto configurado (`lag_ceiling_ms`)."""
    enabled, failure_rate, failure_types = _load_config()
    if not enabled or "kafka_lag" not in failure_types or random.random() >= failure_rate:
        return None
    params = get_active_type_params()
    delay_ms = record_kafka_lag_message(params.lag_increment_ms, params.lag_ceiling_ms)
    return delay_ms / 1000.0


def maybe_kafka_publish_delay_seconds() -> float | None:
    """Chamada pelo producer antes de publicar cada evento. Retorna o
    atraso fixo (segundos) a aplicar desta vez, ou None se kafka_delay
    nao estiver ativo/sorteado agora."""
    enabled, failure_rate, failure_types = _load_config()
    if not enabled or "kafka_delay" not in failure_types or random.random() >= failure_rate:
        return None
    return get_active_type_params().kafka_delay_seconds
