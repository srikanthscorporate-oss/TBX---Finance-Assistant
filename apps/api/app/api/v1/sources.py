"""Bring-your-own MySQL data source: validate, inspect, initialise.

Three steps, matching the Data Source page:

  POST /api/v1/sources/validate    is the endpoint live, and what is in it?
  POST /api/v1/sources/initialize  ingest it and make it the assistant's dataset
  GET  /api/v1/sources/status      progress, then the active source

Credentials are held in memory only, for the life of the process, and are never
returned: `validate` hands back an opaque token that `initialize` redeems.
"""
from __future__ import annotations

import logging
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services import mysql_source as ms
from ...services.ingest import IngestError, Ingestor
from ...services.source_mapping import build_mapping
from ...state import app_state, rebuild_dataset_context

log = logging.getLogger("tbx.sources")

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


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


@router.post("/validate")
async def validate(req: ConnectionRequest) -> dict[str, Any]:
    """Open the connection, list the tables and preview one.

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
        mapping = build_mapping(tables)
        chosen = req.preview_table or _default_preview(tables, mapping)
        table = next((t for t in tables if t.name == chosen), tables[0])
        sample = ms.preview(conn, target.database, table)
    except ms.SourceError as e:
        raise HTTPException(400, str(e)) from None
    finally:
        conn.close()

    token = secrets.token_urlsafe(24)
    app_state.pending_sources[token] = (target, mapping)
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
        "mapping": mapping.public(),
        "can_initialize": mapping.ready and total_rows > 0,
    }


def _default_preview(tables, mapping) -> str:
    """Show the transaction table when one was recognised; it is what the
    assistant will actually answer from."""
    txn = mapping.tables["transaction"].source_table
    if txn:
        return txn
    return max(tables, key=lambda t: t.rows).name


@router.post("/initialize")
async def initialize(req: InitializeRequest) -> dict[str, Any]:
    """Ingest the validated source and hand the chatbot over to it.

    This replaces the dataset currently loaded in ClickHouse. It runs in the
    background; poll /status.
    """
    entry = app_state.pending_sources.get(req.token)
    if not entry:
        raise HTTPException(404, "that connection has expired; validate the endpoint again")
    target, mapping = entry
    if not mapping.ready:
        raise HTTPException(400, "; ".join(mapping.problems()))
    if app_state.ingest.busy:
        raise HTTPException(409, "an initialisation is already running")

    ingestor = Ingestor(target, mapping)

    def _done(progress) -> None:
        """Runs after the last insert; `ready` is set only once this returns cleanly."""
        try:
            rebuild_dataset_context()
            app_state.source = target
            app_state.pending_sources.pop(req.token, None)
            log.info("data source switched to %s (%s)", target.label, progress.dataset_version)
        except Exception as e:  # noqa: BLE001
            progress.state = "failed"
            progress.error = f"loaded, but the assistant could not read it back: {e}"

    try:
        app_state.ingest.start(ingestor, _done)
    except IngestError as e:
        raise HTTPException(409, str(e)) from None
    return {"started": True, "status": ingestor.progress.public()}


@router.get("/status")
async def status() -> dict[str, Any]:
    """Progress of the current or last initialisation, plus the active source."""
    ctx = app_state.ctx
    return {
        "progress": app_state.ingest.progress.public(),
        "active_source": app_state.source.public() if app_state.source else None,
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
