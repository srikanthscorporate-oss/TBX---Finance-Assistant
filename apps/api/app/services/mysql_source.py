"""Read-only MySQL source connector.

The user supplies a live MySQL endpoint on the Data Source page; this module is
the only place that talks to it. Everything here is read-only: connections are
opened with autocommit and every statement is a SELECT or an information_schema
lookup. Identifiers are never interpolated from user text -- a table or column
name may only reach SQL after it has been read back out of information_schema
for that same connection, and it is backtick-quoted on the way in.

Credentials live in memory for the life of the process (app_state.source) and
are never logged, never persisted and never returned by the API.
"""
from __future__ import annotations

import re
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pymysql

DEFAULT_PORT = 3306
CONNECT_TIMEOUT = 8
READ_TIMEOUT = 30
PREVIEW_ROWS = 25
STREAM_BATCH = 5_000

_IDENT_OK = re.compile(r"^[A-Za-z0-9_$ .\-]{1,64}$")


class SourceError(RuntimeError):
    """The endpoint could not be reached, authenticated against, or read."""


@dataclass(frozen=True)
class MySQLTarget:
    """One MySQL endpoint. `password` is excluded from every serialisation below."""

    host: str
    port: int
    database: str
    user: str
    password: str = field(repr=False, default="")

    def public(self) -> dict[str, Any]:
        """What the UI is allowed to see back. No password, ever."""
        return {"host": self.host, "port": self.port,
                "database": self.database, "user": self.user}

    @property
    def label(self) -> str:
        return f"{self.user}@{self.host}:{self.port}/{self.database}"


def parse_endpoint(raw: str) -> dict[str, Any]:
    """Pull whatever the endpoint link already carries.

    Accepts `mysql://user:pass@host:3306/db`, `host:3306/db`, a bare host, or a
    JDBC string (`jdbc:mysql://...`). Returns only the fields actually present,
    so the explicit form fields can fill the rest in.
    """
    text = (raw or "").strip()
    if not text:
        return {}
    if text.lower().startswith("jdbc:"):
        text = text[5:]
    if "://" not in text:
        text = f"mysql://{text}"
    try:
        u = urllib.parse.urlsplit(text)
    except ValueError as e:
        raise SourceError(f"could not parse the endpoint link: {e}") from None

    out: dict[str, Any] = {}
    if u.hostname:
        out["host"] = u.hostname
    if u.port:
        out["port"] = u.port
    if u.username:
        out["user"] = urllib.parse.unquote(u.username)
    if u.password:
        out["password"] = urllib.parse.unquote(u.password)
    db = u.path.lstrip("/").strip()
    if db:
        out["database"] = db.split("/")[0]
    return out


def build_target(*, endpoint: str = "", host: str = "", port: int | None = None,
                 database: str = "", user: str = "", password: str = "") -> MySQLTarget:
    """Merge the endpoint link with the explicit fields; explicit fields win.

    A link that already carries user, password, database and port is enough on
    its own -- that is the "process the connection directly" case.
    """
    parsed = parse_endpoint(endpoint)
    merged_host = str(host or parsed.get("host") or "").strip()
    merged_port = int(port or parsed.get("port") or DEFAULT_PORT)
    merged_db = str(database or parsed.get("database") or "").strip()
    merged_user = str(user or parsed.get("user") or "").strip()
    merged_password = str(password or parsed.get("password") or "")
    missing = [k for k, v in (("host", merged_host), ("database", merged_db),
                              ("user", merged_user)) if not v]
    if missing:
        raise SourceError("missing required connection field(s): " + ", ".join(missing))
    if not (1 <= merged_port <= 65535):
        raise SourceError(f"port out of range: {merged_port}")
    return MySQLTarget(host=merged_host, port=merged_port, database=merged_db,
                       user=merged_user, password=merged_password)


def connect(target: MySQLTarget):
    """Open a read-only connection. Driver errors become SourceError with the
    server's own message, which is what the user needs to fix their input."""
    try:
        return pymysql.connect(
            host=target.host, port=target.port, user=target.user,
            password=target.password, database=target.database,
            connect_timeout=CONNECT_TIMEOUT, read_timeout=READ_TIMEOUT,
            autocommit=True, charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
    except pymysql.MySQLError as e:
        raise SourceError(_explain(e)) from None
    except OSError as e:
        raise SourceError(f"could not reach {target.host}:{target.port} ({e})") from None


def _explain(e: pymysql.MySQLError) -> str:
    code = e.args[0] if e.args else 0
    detail = str(e.args[1]) if len(e.args) > 1 else str(e)
    if code == 1045:
        return "authentication failed: check the user and password"
    if code == 1049:
        return "that database does not exist on the server"
    if code in (2003, 2002):
        return f"the endpoint is not accepting connections ({detail})"
    if code == 1044:
        return "this user has no access to that database"
    return f"MySQL error {code}: {detail}"


def _q(ident: str) -> str:
    """Backtick-quote an identifier that has already been read from information_schema."""
    if not _IDENT_OK.match(ident):
        raise SourceError(f"refusing to use an unsafe identifier: {ident!r}")
    return "`" + ident.replace("`", "") + "`"


@dataclass
class SourceColumn:
    name: str
    data_type: str
    nullable: bool


@dataclass
class SourceTable:
    name: str
    columns: list[SourceColumn]
    rows: int
    """Exact `count()` -- the page shows it as the evidence that data is there."""

    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def public(self) -> dict[str, Any]:
        return {"name": self.name, "rows": self.rows,
                "columns": [{"name": c.name, "type": c.data_type, "nullable": c.nullable}
                            for c in self.columns]}


MAX_TABLES = 200
COUNT_LIMIT_ROWS = 50_000_000
"""Above the information_schema estimate, an exact count is skipped and the
estimate is reported instead so validation cannot hang on a huge table."""


def introspect(conn, database: str) -> list[SourceTable]:
    """Tables, their columns and their row counts, straight from the server."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT TABLE_NAME, TABLE_ROWS FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE' "
            "ORDER BY TABLE_NAME LIMIT %s",
            (database, MAX_TABLES),
        )
        table_rows = cur.fetchall()
        if not table_rows:
            return []
        cur.execute(
            "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE "
            "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s "
            "ORDER BY TABLE_NAME, ORDINAL_POSITION",
            (database,),
        )
        col_rows = cur.fetchall()

    by_table: dict[str, list[SourceColumn]] = {}
    for r in col_rows:
        by_table.setdefault(r["TABLE_NAME"], []).append(
            SourceColumn(r["COLUMN_NAME"], str(r["DATA_TYPE"]), r["IS_NULLABLE"] == "YES"))

    tables: list[SourceTable] = []
    for r in table_rows:
        name = r["TABLE_NAME"]
        estimate = int(r["TABLE_ROWS"] or 0)
        if estimate <= COUNT_LIMIT_ROWS:
            with conn.cursor() as cur:
                cur.execute(f"SELECT count(*) AS n FROM {_q(database)}.{_q(name)}")
                exact = int(cur.fetchone()["n"])
        else:
            exact = estimate
        tables.append(SourceTable(name=name, columns=by_table.get(name, []), rows=exact))
    return tables


def preview(conn, database: str, table: SourceTable, limit: int = PREVIEW_ROWS) -> dict[str, Any]:
    """A first page of rows for the table shown on the Data Source page."""
    cols = ", ".join(_q(c.name) for c in table.columns)
    with conn.cursor() as cur:
        cur.execute(f"SELECT {cols} FROM {_q(database)}.{_q(table.name)} LIMIT %s", (int(limit),))
        rows = cur.fetchall()
    return {"table": table.name, "columns": table.column_names(),
            "rows": [{k: _jsonable(v) for k, v in row.items()} for row in rows]}


def stream(conn, database: str, table: str, columns: list[str],
           batch: int = STREAM_BATCH) -> Iterator[list[dict[str, Any]]]:
    """Yield the table in batches, keyed by the requested column names.

    Server-side cursor: a 20M-row source must not be buffered into the API.
    """
    select = ", ".join(_q(c) for c in columns)
    with conn.cursor(pymysql.cursors.SSDictCursor) as cur:
        cur.execute(f"SELECT {select} FROM {_q(database)}.{_q(table)}")
        while True:
            rows = cur.fetchmany(batch)
            if not rows:
                return
            yield [{k: _jsonable(v) for k, v in row.items()} for row in rows]


def _jsonable(v: Any) -> Any:
    if isinstance(v, (datetime, date)):
        return v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, Decimal):
        return f"{v:f}"
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", "replace")
    return v
