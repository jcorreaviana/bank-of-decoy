import os
from dataclasses import dataclass


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
