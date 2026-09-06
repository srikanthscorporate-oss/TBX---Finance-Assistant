"""Live MySQL data source: validate, connect, status.

The assistant answers directly from a MySQL server; nothing is copied. The Data
Source page validates an endpoint, then `connect` makes it the live source in one
step: the client is swapped, the dataset context is re-read from the new server,
and only if that succeeds does the switch commit.

  POST /api/v1/sources/validate    is the endpoint live, and does it have the schema?
  POST /api/v1/sources/initialize  make it the live source (kept under its old name
                                   so the page's button still works)
  GET  /api/v1/sources/status      the active source
  POST /api/v1/sources/reset       back to the endpoint configured in MYSQL_*

Credentials are held in memory only, for the life of the process, and are never
returned: `validate` hands back an opaque token that `initialize` redeems.
"""
from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...db.mysql import MySQLTarget
from ...services import mysql_source as ms
from ...state import (
    app_state,
    clear_active_source,
    connect_source,
    env_target,
)

log = logging.getLogger("tbx.sources")

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])

LIVE_COLUMNS: dict[str, list[str]] = {
    "bank": ["bank_code", "bank_name"],
    "account": ["account_id", "entity_id", "account_number", "program_id",
                "available_balance", "bank_code"],
    "transaction": ["transaction_id", "account_id", "transaction_date", "transaction_type",
                    "description", "transaction_amount", "transaction_reference_id",
                    "utr_number"],
}
"""Every column the compiler reads. Queries run live, so nothing can be defaulted at
load time: a source missing any of these is reported and refused."""


class ConnectionRequest(BaseModel):
    """The Data Source form. `endpoint` alone is enough when it carries every field."""

    model_config = {"extra": "forbid"}

    endpoint: str = Field(default="", max_length=500)
    host: str = Field(default="", max_length=253)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str = Field(default="", max_length=64)
    user: str = Field(default="", max_length=64)
    password: str = Field(default="", max_length=512)
    preview_table: str | None = Field(default=None, max_length=64)


class InitializeRequest(BaseModel):
    model_config = {"extra": "forbid"}

    token: str = Field(min_length=8, max_length=64)


def _target(req: ConnectionRequest) -> ms.MySQLTarget:
    try:
        return ms.build_target(endpoint=req.endpoint, host=req.host, port=req.port,
                               database=req.database, user=req.user, password=req.password)
    except ms.SourceError as e:
        raise HTTPException(400, str(e)) from None


def _schema_report(tables) -> dict[str, Any]:
    """Which canonical tables and columns the source has, and what is missing."""
    by_name = {t.name: {c.name for c in t.columns} for t in tables}
    report, problems = [], []
    for table, cols in LIVE_COLUMNS.items():
        have = by_name.get(table)
        if have is None:
            report.append({"canonical": table, "present": False, "missing": cols})
            problems.append(f"table `{table}` is missing")
            continue
        missing = [c for c in cols if c not in have]
        report.append({"canonical": table, "present": True, "missing": missing,
                       "rows": next((t.rows for t in tables if t.name == table), 0)})
        if missing:
            problems.append(f"`{table}` lacks {', '.join(missing)}")
    return {"tables": report, "ready": not problems, "problems": problems}


@router.post("/validate")
async def validate(req: ConnectionRequest) -> dict[str, Any]:
    """Open the connection, list the tables, check the schema and preview one table.

    `status` is "data_available" when the endpoint is live and has at least one
    table with rows -- that is the badge the page shows.
    """
    target = _target(req)
    try:
        conn = ms.connect(target)
    except ms.SourceError as e:
        return {"status": "unreachable", "connected": False, "error": str(e),
                "target": target.public()}

    try:
        tables = ms.introspect(conn, target.database)
        if not tables:
            return {"status": "empty", "connected": True, "target": target.public(),
                    "tables": [], "error": "the connection works but the database has no tables"}
        schema = _schema_report(tables)
        chosen = req.preview_table or ("transaction" if "transaction" in
                                       {t.name for t in tables} else tables[0].name)
        table = next((t for t in tables if t.name == chosen), tables[0])
        sample = ms.preview(conn, target.database, table)
    except ms.SourceError as e:
        raise HTTPException(400, str(e)) from None
    finally:
        conn.close()

    token = secrets.token_urlsafe(24)
    app_state.pending_sources[token] = MySQLTarget(
        host=target.host, port=target.port, database=target.database,
        user=target.user, password=target.password)
    total_rows = sum(t.rows for t in tables)
    return {
        "status": "data_available" if total_rows else "empty",
        "connected": True,
        "token": token,
        "target": target.public(),
        "table_count": len(tables),
        "total_rows": total_rows,
        "tables": [t.public() for t in tables],
        "preview": sample,
        "mapping": schema,
        "can_initialize": schema["ready"] and total_rows > 0,
    }


@router.post("/initialize")
async def initialize(req: InitializeRequest) -> dict[str, Any]:
    """Make the validated endpoint the live source. Synchronous: it reads the dataset
    facts from the new server and switches only when that succeeds."""
    target = app_state.pending_sources.get(req.token)
    if not target:
        raise HTTPException(404, "that connection has expired; validate the endpoint again")
    try:
        connect_source(target)
    except Exception as e:  # noqa: BLE001 -- the page needs the reason
        raise HTTPException(502, f"could not read the source: {e}") from None
    app_state.pending_sources.pop(req.token, None)
    return {"started": True, "status": _progress_done()}


def _progress_done() -> dict[str, Any]:
    """Shape the page already understands: a completed, instantaneous load."""
    ctx = app_state.ctx
    return {"state": "ready", "step": "connected", "rows_loaded": {}, "rows_expected": {},
            "percent": 100.0, "busy": False, "error": None,
            "dataset_version": ctx.dataset_version if ctx else None,
            "started_at": None, "finished_at": None, "warnings": []}


@router.get("/status")
async def status() -> dict[str, Any]:
    ctx = app_state.ctx
    return {
        "progress": _progress_done() if ctx else {
            "state": "idle", "step": "", "rows_loaded": {}, "rows_expected": {},
            "percent": 0.0, "busy": False, "error": None, "dataset_version": None,
            "started_at": None, "finished_at": None, "warnings": []},
        "active_source": app_state.source.public() if app_state.source else None,
        "active_database": app_state.source.database if app_state.source else None,
        "bundled": False,
        "live": True,
        "dataset": {
            "dataset_version": ctx.dataset_version,
            "min_date": ctx.calendar.min_date.isoformat(),
            "max_date": ctx.calendar.max_date.isoformat(),
            "accounts": len(ctx.accounts),
            "counterparties": len(ctx.counterparties),
            "entities": len(ctx.entities),
        } if ctx else None,
        "chat_ready": app_state.ready,
    }


@router.post("/reset")
async def reset() -> dict[str, Any]:
    """Back to the endpoint configured in the environment."""
    clear_active_source()
    try:
        connect_source(env_target())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"could not connect to the configured source: {e}") from None
    log.info("data source reset to %s", env_target().label)
    return {"reset": True, "active_database": env_target().database}
