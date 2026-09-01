"""get_settings() le agent-local/.env (issue #81) - necessario porque uma
Scheduled Task do Windows nao herda nenhuma variavel exportada numa sessao
interativa, ao contrario do fluxo manual anterior (operador exportava cada
variavel no terminal antes de rodar `python -m agent_local.polling`)."""

import agent_local.config as config
from agent_local.config import get_settings


def test_get_settings_le_valor_do_env_file_quando_variavel_nao_esta_no_ambiente(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("REPO_URL=https://example.invalid/repo.git\n", encoding="utf-8")
    monkeypatch.setattr(config, "_ENV_FILE", env_file)
    monkeypatch.delenv("REPO_URL", raising=False)

    settings = get_settings()

    assert settings.repo_url == "https://example.invalid/repo.git"


def test_get_settings_variavel_ja_no_ambiente_vence_o_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("REPO_URL=https://do-arquivo.invalid/repo.git\n", encoding="utf-8")
    monkeypatch.setattr(config, "_ENV_FILE", env_file)
    monkeypatch.setenv("REPO_URL", "https://do-ambiente.invalid/repo.git")

    settings = get_settings()

    assert settings.repo_url == "https://do-ambiente.invalid/repo.git"


def test_get_settings_sem_env_file_usa_defaults_normalmente(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_ENV_FILE", tmp_path / "nao-existe.env")
    monkeypatch.delenv("REPO_URL", raising=False)
    monkeypatch.delenv("AGENT_LOCAL_MODEL", raising=False)

    settings = get_settings()

    assert settings.repo_url == ""
    assert settings.model == "claude-sonnet-5"
