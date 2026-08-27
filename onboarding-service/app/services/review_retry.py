"""Logica de retentativa das filas de revisao (specs/business/07-kafka-onboarding-eventos.md).

Escopo desta issue: so o topico e a publicacao (ver onboarding_events.py) -
uma rotina de revisao manual completa (consumidor sempre ativo, UI de
triagem, etc.) fica para uma proxima issue. O que existe aqui e o
utilitario minimo e testavel que decide o comportamento diferenciado que a
spec exige desde ja:

- fila de qualidade: reprocessa a MESMA mensagem ate `max_tentativas` vezes
  antes de desistir (dead-letter apos N tentativas, N definido aqui).
- fila de compliance: NUNCA reprocessa - primeira falha ja vai direto para
  dead-letter (decisao de compliance exige revisao manual; reprocessamento
  automatico poderia mascarar um caso de fraude nao tratado).

Dead-letter, nesta implementacao minima, e publicar o envelope original
(mais o erro) no topico `<topico>.dlq` - nunca descartar a mensagem em
silencio (specs/business/07: "mensagem falha permanece visivel para
intervencao manual").
"""

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

MAX_TENTATIVAS_QUALIDADE = 3


def _publicar_dead_letter(envelope: dict, topico: str, erro: Exception, publish_event: Callable[[str, dict], None]) -> None:
    dlq_envelope = {**envelope, "erro": str(erro)}
    publish_event(f"{topico}.dlq", dlq_envelope)
    logger.error(
        "Mensagem enviada para dead-letter - intervencao manual necessaria.",
        extra={
            "context": {
                "topico": topico,
                "event_id": envelope.get("event_id"),
                "erro": str(erro),
            }
        },
    )


def process_with_retry(
    envelope: dict,
    topico: str,
    handler: Callable[[dict], None],
    publish_event: Callable[[str, dict], None],
    max_tentativas: int = MAX_TENTATIVAS_QUALIDADE,
) -> str:
    """Fila de qualidade: reprocessa ate `max_tentativas` vezes antes do
    dead-letter. Retorna "processado" ou "dead_letter"."""
    ultimo_erro: Exception | None = None
    for tentativa in range(1, max_tentativas + 1):
        try:
            handler(envelope)
            return "processado"
        except Exception as exc:  # noqa: BLE001 - handler e generico/pluggable
            ultimo_erro = exc
            logger.warning(
                "Falha ao processar mensagem de revisao de qualidade - tentativa %s/%s.",
                tentativa,
                max_tentativas,
                extra={
                    "context": {
                        "topico": topico,
                        "event_id": envelope.get("event_id"),
                        "tentativa": tentativa,
                        "max_tentativas": max_tentativas,
                        "erro": str(exc),
                    }
                },
            )

    assert ultimo_erro is not None  # max_tentativas >= 1 garante ao menos uma iteracao
    _publicar_dead_letter(envelope, topico, ultimo_erro, publish_event)
    return "dead_letter"


def process_without_retry(
    envelope: dict,
    topico: str,
    handler: Callable[[dict], None],
    publish_event: Callable[[str, dict], None],
) -> str:
    """Fila de compliance: nenhuma retentativa - primeira falha ja vai
    direto para dead-letter. Retorna "processado" ou "dead_letter"."""
    try:
        handler(envelope)
        return "processado"
    except Exception as exc:  # noqa: BLE001 - handler e generico/pluggable
        _publicar_dead_letter(envelope, topico, exc, publish_event)
        return "dead_letter"
