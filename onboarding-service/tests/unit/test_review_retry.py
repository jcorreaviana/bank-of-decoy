from app.services.review_retry import (
    MAX_TENTATIVAS_QUALIDADE,
    process_with_retry,
    process_without_retry,
)


class _HandlerFalhaNVezes:
    """Duplo de handler: falha nas primeiras `falhas` chamadas, depois sucede."""

    def __init__(self, falhas: int) -> None:
        self.falhas = falhas
        self.chamadas = 0

    def __call__(self, _envelope: dict) -> None:
        self.chamadas += 1
        if self.chamadas <= self.falhas:
            raise ValueError(f"falha simulada {self.chamadas}")


def test_process_with_retry_sucede_apos_falhas_dentro_do_limite() -> None:
    handler = _HandlerFalhaNVezes(falhas=2)
    publicados = []

    resultado = process_with_retry(
        {"event_id": "e1"}, "onboarding.revisao_qualidade", handler, lambda t, e: publicados.append((t, e))
    )

    assert resultado == "processado"
    assert handler.chamadas == 3
    assert publicados == []


def test_process_with_retry_vai_para_dead_letter_apos_esgotar_tentativas() -> None:
    handler = _HandlerFalhaNVezes(falhas=MAX_TENTATIVAS_QUALIDADE + 5)
    publicados = []

    resultado = process_with_retry(
        {"event_id": "e2"}, "onboarding.revisao_qualidade", handler, lambda t, e: publicados.append((t, e))
    )

    assert resultado == "dead_letter"
    assert handler.chamadas == MAX_TENTATIVAS_QUALIDADE  # nunca excede o limite
    assert len(publicados) == 1
    topico, envelope = publicados[0]
    assert topico == "onboarding.revisao_qualidade.dlq"
    assert envelope["event_id"] == "e2"
    assert "erro" in envelope


def test_process_without_retry_sucede_de_primeira() -> None:
    handler = _HandlerFalhaNVezes(falhas=0)
    publicados = []

    resultado = process_without_retry(
        {"event_id": "e3"}, "onboarding.revisao_compliance", handler, lambda t, e: publicados.append((t, e))
    )

    assert resultado == "processado"
    assert handler.chamadas == 1
    assert publicados == []


def test_process_without_retry_vai_direto_para_dead_letter_sem_reprocessar() -> None:
    handler = _HandlerFalhaNVezes(falhas=99)
    publicados = []

    resultado = process_without_retry(
        {"event_id": "e4"}, "onboarding.revisao_compliance", handler, lambda t, e: publicados.append((t, e))
    )

    assert resultado == "dead_letter"
    assert handler.chamadas == 1  # nunca reprocessa, mesmo com falhas subsequentes disponiveis
    assert len(publicados) == 1
    assert publicados[0][0] == "onboarding.revisao_compliance.dlq"
