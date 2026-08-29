import httpx
import pytest
from unittest.mock import patch

from agent_preditivo.chaos_status import TOKEN_ENV_VAR, TOKEN_HEADER, is_chaos_enabled


def _completed(stdout: str, returncode: int = 0):
    class _Result:
        pass

    result = _Result()
    result.stdout = stdout
    result.returncode = returncode
    return result


# --- mecanismo antigo (docker inspect / CHAOS_ENABLED), sem base_url ---
# is_chaos_enabled(service) sem base_url so usa esse caminho - mantido
# para retrocompatibilidade (ex. scripts/validate_chaos_pipeline_e2e.sh).


def test_is_chaos_enabled_true_quando_env_var_presente() -> None:
    stdout = "SERVICE_NAME=transaction-service\nCHAOS_ENABLED=true\nCHAOS_FAILURE_RATE=0.5\n"
    with patch("agent_preditivo.chaos_status.subprocess.run", return_value=_completed(stdout)):
        assert is_chaos_enabled("transaction-service") is True


def test_is_chaos_enabled_false_quando_env_var_false() -> None:
    stdout = "SERVICE_NAME=transaction-service\nCHAOS_ENABLED=false\n"
    with patch("agent_preditivo.chaos_status.subprocess.run", return_value=_completed(stdout)):
        assert is_chaos_enabled("transaction-service") is False


def test_is_chaos_enabled_false_quando_env_var_ausente() -> None:
    stdout = "SERVICE_NAME=transaction-service\n"
    with patch("agent_preditivo.chaos_status.subprocess.run", return_value=_completed(stdout)):
        assert is_chaos_enabled("transaction-service") is False


def test_is_chaos_enabled_false_quando_docker_retorna_erro() -> None:
    with patch("agent_preditivo.chaos_status.subprocess.run", return_value=_completed("", returncode=1)):
        assert is_chaos_enabled("servico-inexistente") is False


def test_is_chaos_enabled_false_quando_docker_ausente() -> None:
    with patch("agent_preditivo.chaos_status.subprocess.run", side_effect=FileNotFoundError()):
        assert is_chaos_enabled("transaction-service") is False


# --- mecanismo novo (GET /internal/chaos/status, issue #57), com base_url ---
# Nucleo do achado da issue #57: caos ativado SO via POST
# /internal/chaos/config (nunca a variavel de ambiente estatica) precisa
# ser detectado corretamente quando base_url e passado.


def test_is_chaos_enabled_usa_endpoint_quando_token_e_base_url_presentes(monkeypatch) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "s3cret")

    def fake_get(url, *, headers, timeout):
        assert url == "http://localhost:8002/internal/chaos/status"
        assert headers[TOKEN_HEADER] == "s3cret"
        return httpx.Response(200, json={"enabled": True, "failure_rate": 1.0, "failure_types": ["kafka_delay"]})

    with patch("agent_preditivo.chaos_status.httpx.get", side_effect=fake_get):
        with patch("agent_preditivo.chaos_status.subprocess.run") as mock_docker:
            assert is_chaos_enabled("account-service", base_url="http://localhost:8002") is True
    mock_docker.assert_not_called()


def test_is_chaos_enabled_false_via_endpoint_quando_enabled_false(monkeypatch) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "s3cret")

    def fake_get(url, *, headers, timeout):
        return httpx.Response(200, json={"enabled": False, "failure_rate": 0.05, "failure_types": []})

    with patch("agent_preditivo.chaos_status.httpx.get", side_effect=fake_get):
        assert is_chaos_enabled("account-service", base_url="http://localhost:8002") is False


def test_is_chaos_enabled_cai_para_docker_inspect_sem_token(monkeypatch) -> None:
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    stdout = "CHAOS_ENABLED=true\n"

    with patch("agent_preditivo.chaos_status.httpx.get") as mock_get:
        with patch("agent_preditivo.chaos_status.subprocess.run", return_value=_completed(stdout)):
            assert is_chaos_enabled("account-service", base_url="http://localhost:8002") is True
    mock_get.assert_not_called()


def test_is_chaos_enabled_cai_para_docker_inspect_em_erro_de_rede(monkeypatch) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "s3cret")
    stdout = "CHAOS_ENABLED=true\n"

    with patch("agent_preditivo.chaos_status.httpx.get", side_effect=httpx.ConnectError("recusado")):
        with patch("agent_preditivo.chaos_status.subprocess.run", return_value=_completed(stdout)):
            assert is_chaos_enabled("account-service", base_url="http://localhost:8002") is True


def test_is_chaos_enabled_cai_para_docker_inspect_em_status_nao_200(monkeypatch) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "s3cret")
    stdout = "CHAOS_ENABLED=false\n"

    def fake_get(url, *, headers, timeout):
        return httpx.Response(403, json={"error_code": "CHAOS_CONFIG_FORBIDDEN"})

    with patch("agent_preditivo.chaos_status.httpx.get", side_effect=fake_get):
        with patch("agent_preditivo.chaos_status.subprocess.run", return_value=_completed(stdout)):
            assert is_chaos_enabled("account-service", base_url="http://localhost:8002") is False


def test_is_chaos_enabled_ignora_endpoint_quando_base_url_nao_informado(monkeypatch) -> None:
    monkeypatch.setenv(TOKEN_ENV_VAR, "s3cret")
    stdout = "CHAOS_ENABLED=true\n"

    with patch("agent_preditivo.chaos_status.httpx.get") as mock_get:
        with patch("agent_preditivo.chaos_status.subprocess.run", return_value=_completed(stdout)):
            assert is_chaos_enabled("account-service") is True
    mock_get.assert_not_called()
