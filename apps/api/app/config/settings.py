"""Configuration, read from the environment."""
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
    """Connection facts for the live source come from MYSQL_*; nothing is ever written to it."""
    env: str = field(default_factory=lambda: os.getenv("TBX_ENV", "development"))
    domain: str = field(default_factory=lambda: os.getenv("TBX_DOMAIN", "localhost"))
    dataset_version: str = field(default_factory=lambda: os.getenv("DATASET_VERSION", "unknown"))

    # The live MySQL source the assistant answers from. Read-only account expected.
    mysql_host: str = field(default_factory=lambda: os.getenv("MYSQL_HOST", "mysql"))
    mysql_port: int = field(default_factory=lambda: _int("MYSQL_PORT", 3306))
    mysql_db: str = field(default_factory=lambda: os.getenv("MYSQL_DB", "tbx_app"))
    mysql_user: str = field(default_factory=lambda: os.getenv("MYSQL_USER", "tbx"))
    mysql_password: str = field(default_factory=lambda: os.getenv("MYSQL_PASSWORD", ""))

    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", "redis://redis:6379/0"))

    query_timeout: int = field(default_factory=lambda: _int("QUERY_TIMEOUT_SECONDS", 90))
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
