import logging
from unittest.mock import patch

from agent_preditivo.config import Settings
from agent_preditivo.polling import run_bug_cycle, run_cycle


def test_run_bug_cycle_repassa_base_url_de_cada_servico() -> None:
    """issue #57: run_bug_cycle precisa passar a URL de cada servico para
    detect_bugs_for_service, senao is_chaos_enabled() nunca consegue
    consultar GET /internal/chaos/status."""
    settings = Settings(
        interval_seconds=300,
        prometheus_url="http://localhost:9090",
        agent_ops_database_url="postgresql://bank:bank@localhost:5432/agent_ops",
        ollama_model="llama3.2:3b",
        services=["account-service"],
        api_base_urls={"account-service": "http://localhost:8002"},
        log_level="INFO",
    )
    with (
        patch("agent_preditivo.polling.get_settings", return_value=settings),
        patch("agent_preditivo.polling.detect_bugs_for_service", return_value=[]) as mock_detect,
    ):
        run_bug_cycle()

    mock_detect.assert_called_once_with("account-service", base_url="http://localhost:8002")


def test_run_cycle_erro_e_notificado_e_nao_propaga() -> None:
    """Regressao critica: um erro num ciclo (Ollama fora do ar, etc.) nao
    pode derrubar o loop de polling - deve ser notificado e o processo
    segue vivo para o proximo ciclo."""
    with (
        patch("agent_preditivo.polling.run_bug_cycle", side_effect=RuntimeError("Ollama indisponível")),
        patch("agent_preditivo.polling.notify_agent_error") as mock_notify,
    ):
        run_cycle(include_opportunity=False)  # nao deve levantar

    mock_notify.assert_called_once()
    assert mock_notify.call_args.args[0] == "agent-preditivo"
    assert "Ollama indisponível" in mock_notify.call_args.args[1]


def test_run_cycle_sem_erro_nao_notifica() -> None:
    with (
        patch("agent_preditivo.polling.run_bug_cycle", return_value=[]),
        patch("agent_preditivo.polling.notify_agent_error") as mock_notify,
    ):
        run_cycle(include_opportunity=False)

    mock_notify.assert_not_called()


def test_run_cycle_sucesso_loga_inicio_e_fim(caplog) -> None:
    """Issue #33: ciclo sem achado nenhum (caminho feliz) nao pode ficar
    silencioso - precisa logar inicio e conclusao mesmo sem notificacao."""
    with (
        caplog.at_level(logging.INFO, logger="agent_preditivo.polling"),
        patch("agent_preditivo.polling.run_bug_cycle", return_value=[]),
        patch("agent_preditivo.polling.notify_agent_error"),
    ):
        run_cycle(include_opportunity=False)

    messages = [record.message for record in caplog.records]
    assert any("iniciado" in m for m in messages)
    assert any("concluído com sucesso" in m for m in messages)
