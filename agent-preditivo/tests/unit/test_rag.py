"""Teste de integracao do RAG real (baixa/roda o modelo de embedding de
verdade) - mais lento que os demais testes unitarios, mas e o unico jeito
de validar que a indexacao/busca por similaridade funciona de fato contra
specs/business/ real."""

from agent_preditivo import rag


def test_ingest_and_search_specs_encontra_secao_relevante() -> None:
    total_chunks = rag.ingest_specs()
    assert total_chunks > 0

    results = rag.search_specs("chave PIX de destino inexistente ou cancelada em transação", top_k=3)

    assert len(results) > 0
    assert any("15-validacao-chave-destino.md" in r["file"] or "06-pixkey-transaction-crud.md" in r["file"] for r in results)


def test_search_specs_query_sem_relacao_com_o_dominio_pode_ficar_vazia_ou_distante() -> None:
    rag.ingest_specs()
    results_relevante = rag.search_specs("saldo insuficiente em transação PIX")
    results_irrelevante = rag.search_specs("receita de bolo de chocolate")

    menor_distancia_relevante = results_relevante[0]["distance"] if results_relevante else float("inf")
    menor_distancia_irrelevante = results_irrelevante[0]["distance"] if results_irrelevante else float("inf")

    assert menor_distancia_relevante < menor_distancia_irrelevante
