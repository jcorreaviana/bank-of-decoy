import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Caminho derivado do proprio modulo (nao do cwd de quem inicia o daemon) -
# mesmo principio ja usado em logging_config.py para _LOG_FILE. Sem isso, o
# daemon so enxergava agent-local/.env se o operador exportasse cada
# variavel manualmente no terminal antes de rodar `python -m
# agent_local.polling` - inviavel sob uma Scheduled Task do Windows (issue
# #81), que nao herda nenhuma variavel exportada numa sessao interativa.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


@dataclass(frozen=True)
class Settings:
    interval_seconds: int
    model: str
    max_turns: int
    sdk_timeout_seconds: float
    max_consecutive_failures: int
    agent_ops_database_url: str
    repo_url: str
    repo_clone_dir: str
    test_database_host: str
    test_database_port: str
    log_level: str


def get_settings() -> Settings:
    # `override=False` (default): uma variavel ja presente no ambiente do
    # processo (ex. setada por um teste, ou persistida no registro do
    # Windows) sempre vence o valor do .env, nunca o contrario.
    load_dotenv(_ENV_FILE, override=False)
    return Settings(
        interval_seconds=int(os.environ.get("AGENT_LOCAL_INTERVAL_SECONDS", "300")),
        model=os.environ.get("AGENT_LOCAL_MODEL", "claude-sonnet-5"),
        max_turns=int(os.environ.get("AGENT_LOCAL_MAX_TURNS", "50")),
        sdk_timeout_seconds=float(os.environ.get("AGENT_LOCAL_SDK_TIMEOUT_SECONDS", "1800")),
        max_consecutive_failures=int(os.environ.get("AGENT_LOCAL_MAX_CONSECUTIVE_FAILURES", "3")),
        agent_ops_database_url=os.environ.get(
            "AGENT_OPS_DATABASE_URL", "postgresql://bank:bank@localhost:5432/agent_ops"
        ),
        repo_url=os.environ.get("REPO_URL", ""),
        repo_clone_dir=os.environ.get("REPO_CLONE_DIR", "./workspace/bank-of-decoy"),
        test_database_host=os.environ.get("TEST_DATABASE_HOST", "localhost"),
        test_database_port=os.environ.get("TEST_DATABASE_PORT", "5433"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
