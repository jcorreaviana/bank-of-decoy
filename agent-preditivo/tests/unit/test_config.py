"""get_settings() le agent-preditivo/.env (issue #81) - necessario porque
uma Scheduled Task do Windows nao herda nenhuma variavel exportada numa
sessao interativa, ao contrario do fluxo manual anterior (operador
exportava cada variavel no terminal antes de rodar `python -m
agent_preditivo.polling`)."""

import agent_preditivo.config as config
from agent_preditivo.config import get_settings


def test_get_settings_le_valor_do_env_file_quando_variavel_nao_esta_no_ambiente(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("PREDICTIVE_AGENT_MODEL=llama3.2:1b\n", encoding="utf-8")
    monkeypatch.setattr(config, "_ENV_FILE", env_file)
    monkeypatch.delenv("PREDICTIVE_AGENT_MODEL", raising=False)

    settings = get_settings()

    assert settings.ollama_model == "llama3.2:1b"


def test_get_settings_variavel_ja_no_ambiente_vence_o_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("PREDICTIVE_AGENT_MODEL=do-arquivo\n", encoding="utf-8")
    monkeypatch.setattr(config, "_ENV_FILE", env_file)
    monkeypatch.setenv("PREDICTIVE_AGENT_MODEL", "do-ambiente")

    settings = get_settings()

    assert settings.ollama_model == "do-ambiente"


def test_get_settings_sem_env_file_usa_defaults_normalmente(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_ENV_FILE", tmp_path / "nao-existe.env")
    monkeypatch.delenv("PREDICTIVE_AGENT_MODEL", raising=False)

    settings = get_settings()

    assert settings.ollama_model == "llama3.2:3b"
