import os
from dataclasses import dataclass

from kafka_dlt import DEFAULT_MAX_RETRIES


@dataclass(frozen=True)
class Settings:
    service_name: str
    port: int
    log_level: str
    database_url: str
    kafka_bootstrap_servers: str
    kafka_max_retries: int
    onboarding_service_url: str


def get_settings() -> Settings:
    return Settings(
        service_name=os.environ.get("SERVICE_NAME", "account-service"),
        port=int(os.environ.get("PORT", "8002")),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        database_url=os.environ.get("DATABASE_URL", ""),
        kafka_bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", ""),
        kafka_max_retries=int(os.environ.get("KAFKA_MAX_RETRIES", str(DEFAULT_MAX_RETRIES))),
        onboarding_service_url=os.environ.get("ONBOARDING_SERVICE_URL", ""),
    )
