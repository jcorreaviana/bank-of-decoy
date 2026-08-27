import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    service_name: str
    port: int
    log_level: str
    database_url: str
    kafka_bootstrap_servers: str
    account_service_url: str
    pix_key_service_url: str


def get_settings() -> Settings:
    return Settings(
        service_name=os.environ.get("SERVICE_NAME", "transaction-service"),
        port=int(os.environ.get("PORT", "8004")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        database_url=os.environ.get("DATABASE_URL", ""),
        kafka_bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", ""),
        account_service_url=os.environ.get("ACCOUNT_SERVICE_URL", ""),
        pix_key_service_url=os.environ.get("PIX_KEY_SERVICE_URL", ""),
    )
