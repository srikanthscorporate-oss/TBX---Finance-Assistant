"""Read-only client for the live MySQL source the assistant answers from.

Same contract as the ClickHouse client it replaces: `query(sql, params)` returns a
`QueryResult` whose rows are plain dicts of JSON-safe scalars, so the pipeline,
verification, evidence builder and caches are unchanged.

Safety properties, in order:
  * every session is `READ ONLY` and the account is expected to hold SELECT only;
  * every value travels as a `%(name)s` placeholder that the driver escapes -- SQL text
    produced by the compiler never contains a plan value;
  * every statement carries `MAX_EXECUTION_TIME`, so a question that would scan too much
    of the remote table fails into the error state instead of hanging the turn;
  * the result set is capped, and overflow is an error rather than a silent truncation.

Rows are normalised to the shapes the ClickHouse JSON output produced (Decimal and
temporal values as strings) so downstream formatting is byte-for-byte unchanged.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pymysql
import pymysql.cursors

log = logging.getLogger("tbx.db.mysql")


class QueryError(RuntimeError):
    pass


@dataclass
class QueryResult:
    rows: list[dict[str, Any]]
    duration_ms: float
    rows_read: int = 0
    bytes_read: int = 0


@dataclass(frozen=True)
class MySQLTarget:
    """Connection identity. `public()` is the only form that leaves the process."""
    host: str
    port: int
    database: str
    user: str
    password: str = ""

    @property
    def label(self) -> str:
        return f"{self.host}:{self.port}/{self.database}"

    def public(self) -> dict[str, Any]:
        return {"host": self.host, "port": self.port, "database": self.database, "user": self.user}


class MySQLClient:
    def __init__(self, target: MySQLTarget, *, timeout: int = 60,
                 max_result_rows: int = 50_000, connect_timeout: int = 10):
        self.target = target
        self.timeout = timeout
        self.max_result_rows = max_result_rows
        self.connect_timeout = connect_timeout

    # A connection per statement: the link to the source is slow and occasionally
    # drops mid-stream, and a pooled connection that died leaves the next question
    # with a protocol error instead of a clean retry.
    def _connect(self):
        try:
            return pymysql.connect(
                host=self.target.host, port=self.target.port, user=self.target.user,
                password=self.target.password, database=self.target.database,
                connect_timeout=self.connect_timeout, read_timeout=self.timeout + 5,
                write_timeout=self.timeout, autocommit=True, charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
            )
        except pymysql.MySQLError as e:
            raise QueryError(f"MySQL unreachable: {_msg(e)}") from None

    def query(self, sql: str, params: dict[str, Any] | None = None) -> QueryResult:
        started = datetime.now()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SET SESSION TRANSACTION READ ONLY")
                cur.execute("SET SESSION MAX_EXECUTION_TIME = %(ms)s",
                            {"ms": int(self.timeout * 1000)})
                cur.execute(sql, {k: _encode(v) for k, v in (params or {}).items()})
                rows = cur.fetchmany(self.max_result_rows + 1)
                if len(rows) > self.max_result_rows:
                    raise QueryError(
                        f"result exceeds {self.max_result_rows} rows; narrow the question")
        except pymysql.MySQLError as e:
            raise QueryError(f"MySQL rejected the query: {_msg(e)}") from None
        finally:
            conn.close()
        duration = (datetime.now() - started).total_seconds() * 1000
        out = [{k: _normalise(v) for k, v in r.items()} for r in rows]
        return QueryResult(rows=out, duration_ms=round(duration, 2), rows_read=len(out))

    def ping(self) -> bool:
        try:
            conn = self._connect()
        except QueryError:
            return False
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
            return True
        except pymysql.MySQLError:
            return False
        finally:
            conn.close()


def _encode(value: Any) -> Any:
    """Values the driver binds. Dates stay dates (pymysql quotes them); Decimals and
    bools are passed through."""
    if isinstance(value, timedelta):
        return value.total_seconds()
    return value


def _normalise(value: Any) -> Any:
    if isinstance(value, Decimal):
        return f"{value:f}"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return value


def _msg(e: BaseException) -> str:
    args = getattr(e, "args", ())
    if len(args) >= 2:
        return str(args[1])
    return str(e)
