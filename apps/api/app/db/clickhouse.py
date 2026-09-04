"""Minimal ClickHouse HTTP client.

Uses server-side bound parameters (`{name:Type}` + `param_<name>`) exclusively.
There is no method on this class that accepts an already-interpolated query, by
design -- the compiler hands over SQL and params separately and they stay
separate all the way to the wire.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any


class QueryError(RuntimeError):
    pass


@dataclass
class QueryResult:
    rows: list[dict[str, Any]]
    duration_ms: float
    rows_read: int = 0
    bytes_read: int = 0


class ClickHouseClient:
    def __init__(self, host: str, port: int, user: str, password: str,
                 database: str = "tbx_finance", *, timeout: int = 10,
                 max_result_rows: int = 50_000, secure: bool = False,
                 max_rows_to_read: int = 100_000_000):
        scheme = "https" if secure else "http"
        self.base = f"{scheme}://{host}:{port}"
        self.user, self.password, self.database = user, password, database
        self.timeout = timeout
        self.max_result_rows = max_result_rows
        self.max_rows_to_read = max_rows_to_read

    def query(self, sql: str, params: dict[str, Any] | None = None) -> QueryResult:
        """Run a read query. `params` are bound server-side, never interpolated."""
        qs: dict[str, str] = {
            "database": self.database,
            "default_format": "JSON",
            # Application-level ceilings. The read-only user's settings profile
            # enforces its own, which these cannot exceed.
            "max_execution_time": str(self.timeout),
            "max_result_rows": str(self.max_result_rows),
            # Bound a runaway scan without rejecting a full pass over the 20M
            # rows the prototype is tested at (granule reads can exceed the
            # nominal count, so the ceiling sits well above it).
            "max_rows_to_read": str(self.max_rows_to_read),
            "result_overflow_mode": "throw",
            "readonly": "1",
        }
        for key, value in (params or {}).items():
            qs[f"param_{key}"] = _encode(value)

        url = f"{self.base}/?{urllib.parse.urlencode(qs)}"
        req = urllib.request.Request(url, data=sql.encode(), method="POST")
        req.add_header("X-ClickHouse-User", self.user)
        req.add_header("X-ClickHouse-Key", self.password)

        started = datetime.now()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout + 5) as resp:
                payload = json.loads(resp.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:500]
            raise QueryError(f"ClickHouse rejected the query: {detail}") from None
        except urllib.error.URLError as e:
            raise QueryError(f"ClickHouse unreachable: {e.reason}") from None

        duration = (datetime.now() - started).total_seconds() * 1000
        stats = payload.get("statistics", {})
        return QueryResult(
            rows=payload.get("data", []),
            duration_ms=round(duration, 2),
            rows_read=int(stats.get("rows_read", 0)),
            bytes_read=int(stats.get("bytes_read", 0)),
        )

    def ping(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.base}/ping", timeout=3) as r:
                return r.read().strip() == b"Ok."
        except Exception:
            return False


def _encode(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat(sep=" ") if isinstance(value, datetime) else value.isoformat()
    if isinstance(value, Decimal):
        return f"{value:f}"
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)
