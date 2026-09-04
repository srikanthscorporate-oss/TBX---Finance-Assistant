"""Configuration. Every value comes from the environment; nothing is hardcoded."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.getenv("TBX_ENV", "development"))
    domain: str = field(default_factory=lambda: os.getenv("TBX_DOMAIN", "localhost"))
    dataset_version: str = field(default_factory=lambda: os.getenv("DATASET_VERSION", "unknown"))

    ch_host: str = field(default_factory=lambda: os.getenv("CH_HOST", "clickhouse"))
    ch_port: int = field(default_factory=lambda: _int("CH_PORT", 8123))
    ch_db: str = field(default_factory=lambda: os.getenv("CH_DB", "tbx_finance"))
    # The API uses the read-only agent user in production. The admin user is only
    # ever used by the ingestion script.
    ch_user: str = field(default_factory=lambda: os.getenv("CH_AGENT_USER", "tbx_agent"))
    ch_password: str = field(default_factory=lambda: os.getenv("CH_AGENT_PASSWORD", ""))

    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://redis:6379/0"))

    query_timeout: int = field(default_factory=lambda: _int("QUERY_TIMEOUT_SECONDS", 10))
    max_query_rows: int = field(default_factory=lambda: _int("MAX_QUERY_ROWS", 1000))
    llm_timeout: int = field(default_factory=lambda: _int("LLM_TIMEOUT_SECONDS", 20))
    rate_limit_per_minute: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MINUTE", 30))
    session_ttl_seconds: int = field(default_factory=lambda: _int("SESSION_TTL_SECONDS", 14400))

    allowed_origins: list[str] = field(default_factory=lambda: [
        o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()
    ])

    @property
    def is_production(self) -> bool:
        return self.env == "production"


settings = Settings()
