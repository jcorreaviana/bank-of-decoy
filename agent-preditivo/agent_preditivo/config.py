import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Caminho derivado do proprio modulo (nao do cwd de quem inicia o daemon) -
# mesmo principio ja usado em logging_config.py para _LOG_FILE e replicado
# de agent_local/config.py (issue #81). Sem isso, este daemon so enxergava
# agent-preditivo/.env se o operador exportasse cada variavel manualmente
# no terminal - inviavel sob uma Scheduled Task do Windows, que nao herda
# nenhuma variavel exportada numa sessao interativa.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


@dataclass(frozen=True)
class Settings:
    interval_seconds: int
    prometheus_url: str
    agent_ops_database_url: str
    ollama_model: str
    services: list[str]
    api_base_urls: dict[str, str]
    log_level: str


DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_SERVICES = ["onboarding-service", "account-service", "pix-key-service", "transaction-service"]
DEFAULT_CONTAINER_PREFIX = "bank-of-decoy-"


def _api_base_urls() -> dict[str, str]:
    return {
        "onboarding-service": os.environ.get("ONBOARDING_SERVICE_URL", "http://localhost:8001"),
        "account-service": os.environ.get("ACCOUNT_SERVICE_URL", "http://localhost:8002"),
        "pix-key-service": os.environ.get("PIX_KEY_SERVICE_URL", "http://localhost:8003"),
        "transaction-service": os.environ.get("TRANSACTION_SERVICE_URL", "http://localhost:8004"),
    }


def get_settings() -> Settings:
    # `override=False` (default): uma variavel ja presente no ambiente do
    # processo (ex. setada por um teste, ou persistida no registro do
    # Windows) sempre vence o valor do .env, nunca o contrario.
    load_dotenv(_ENV_FILE, override=False)
    return Settings(
        interval_seconds=int(os.environ.get("PREDICTIVE_AGENT_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS))),
        prometheus_url=os.environ.get("PROMETHEUS_URL", "http://localhost:9090"),
        agent_ops_database_url=os.environ.get(
            "AGENT_OPS_DATABASE_URL", "postgresql://bank:bank@localhost:5432/agent_ops"
        ),
        ollama_model=os.environ.get("PREDICTIVE_AGENT_MODEL", "llama3.2:3b"),
        services=DEFAULT_SERVICES,
        api_base_urls=_api_base_urls(),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )
