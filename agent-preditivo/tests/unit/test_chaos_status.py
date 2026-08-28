from unittest.mock import patch

from agent_preditivo.chaos_status import is_chaos_enabled


def _completed(stdout: str, returncode: int = 0):
    class _Result:
        pass

    result = _Result()
    result.stdout = stdout
    result.returncode = returncode
    return result


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
