from unittest.mock import patch

from agent_preditivo.prometheus_client import fetch_golden_signals


def _mock_instant_query(values: dict[str, float | None]):
    """`_instant_query` e chamado com (prometheus_url, promql) - despacha
    pela substring mais especifica presente na query."""

    def _dispatch(_prometheus_url, promql):
        for key, value in values.items():
            if key in promql:
                return value
        raise AssertionError(f"query inesperada em teste: {promql}")

    return _dispatch


def test_fetch_golden_signals_sem_nenhum_5xx_na_janela_nao_estoura() -> None:
    """Regressao: quando o servico esta saudavel (nenhuma amostra 5xx),
    Prometheus retorna vetor vazio para a query filtrada por status_code -
    _instant_query devolve None, nao 0.0. taxa_erro precisa tratar isso
    sem lancar TypeError (bug real encontrado validando o loop de polling
    ponta a ponta)."""
    values = {
        'status_code=~"5.."': None,
        "http_requests_total": 12.5,
        "db_pool_connections_in_use": None,
        "http_request_duration_seconds_bucket": 0.05,
    }
    with patch("agent_preditivo.prometheus_client._instant_query", side_effect=_mock_instant_query(values)):
        signals = fetch_golden_signals("transaction-service", prometheus_url="http://x")

    assert signals.taxa_erro == 0.0


def test_fetch_golden_signals_sem_trafego_nenhum_nao_estoura() -> None:
    with patch("agent_preditivo.prometheus_client._instant_query", return_value=None):
        signals = fetch_golden_signals("transaction-service", prometheus_url="http://x")

    assert signals.taxa_erro == 0.0
    assert signals.latencia_p95_atual is None
    assert signals.saturacao_pool == 0.0


def test_fetch_golden_signals_calcula_taxa_erro_com_5xx_presentes() -> None:
    values = {
        'status_code=~"5.."': 5.0,
        "http_requests_total": 10.0,
        "db_pool_connections_in_use": 2.0,
        "http_request_duration_seconds_bucket": 0.5,
    }
    with patch("agent_preditivo.prometheus_client._instant_query", side_effect=_mock_instant_query(values)):
        signals = fetch_golden_signals("transaction-service", prometheus_url="http://x")

    assert signals.taxa_erro == 0.5
