import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    service_name: str
    database_url: str


def get_settings() -> Settings:
    return Settings(
        service_name=os.environ.get("SERVICE_NAME", "agent-ops-service"),
        database_url=os.environ.get("DATABASE_URL", ""),
    )
