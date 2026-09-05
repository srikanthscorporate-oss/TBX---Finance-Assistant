"""Read-only browse endpoints and CSV export, through the same compiler and executor as chat."""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from ...contracts.enums import GroupBy, Intent, Metric
from ...contracts.plan import DateRange, FinanceQueryPlan
from ...services.compiler import compile_plan
from ...services.dates import resolve
from ...state import app_state

router = APIRouter(prefix="/api/v1", tags=["data"])


def _require_ready():
    if not app_state.ready:
        raise HTTPException(503, "dataset not loaded")


@router.get("/entities")
async def entities() -> list[dict[str, Any]]:
    """Customer entities in the records, most active first; the UI's scope selector."""
    _require_ready()
    ctx = app_state.ctx
    per_entity: dict[str, int] = {}
    for a in ctx.accounts:
        per_entity[a.entity_id] = per_entity.get(a.entity_id, 0) + 1
    return [{"entity_id": e, "accounts": per_entity.get(e, 0),
             "default": e == ctx.default_entity} for e in ctx.entities]


@router.get("/accounts")
async def accounts(entity_id: str | None = None) -> list[dict[str, Any]]:
    """Accounts with masked numbers only; the encrypted number never leaves the database."""
    _require_ready()
    return [
        {"account_id": a.account_id, "entity_id": a.entity_id, "account": a.masked,
         "bank_code": a.bank_code, "bank_name": a.bank_name, "program_id": a.program_id,
         "available_balance": a.available_balance}
        for a in app_state.ctx.accounts_for(entity_id)
    ]


@router.get("/counterparties")
async def counterparties(entity_id: str | None = None,
                         limit: int = Query(default=50, ge=1, le=500)) -> list[dict[str, Any]]:
    _require_ready()
    return [
        {"name": c.name, "transactions": c.txn_count, "channel": c.channel}
        for c in app_state.ctx.counterparties_for(entity_id)[:limit]
    ]


@router.get("/dataset")
async def dataset() -> dict[str, Any]:
    """The dataset's own date bounds; relative periods anchor to these, not to today."""
    _require_ready()
    ctx = app_state.ctx
    return {
        "dataset_version": ctx.dataset_version,
        "min_date": ctx.calendar.min_date.isoformat(),
        "max_date": ctx.calendar.max_date.isoformat(),
        "currency": ctx.currency,
        "account_count": len(ctx.accounts),
        "counterparty_count": len(ctx.counterparties),
        "entity_count": len(ctx.entities),
        "banks": ctx.banks,
    }


@router.get("/transactions")
async def transactions(
    entity_id: str | None = None,
    counterparty: str | None = None,
    channel: str | None = None,
    transaction_type: str | None = None,
    relative: str | None = Query(default="last_30_days"),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    """Recent transactions through the same compiler and masking as chat."""
    _require_ready()
    ctx = app_state.ctx
    try:
        plan = FinanceQueryPlan(
            intent=Intent.TRANSACTION_LOOKUP, entity_id=entity_id or ctx.default_entity,
            counterparty=counterparty, channel=channel, transaction_type=transaction_type,
            date_range=resolve(DateRange(relative=relative), ctx.calendar) if relative else None,
            limit=limit)  # type: ignore[arg-type]
        cq = compile_plan(plan)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"invalid request: {e}") from None
    result = app_state.ch.query(cq.sql, cq.params)
    rows = app_state.pipeline().evidence._records(plan, cq, result.rows, ctx.currency)
    return {"rows": rows, "count": len(rows), "duration_ms": result.duration_ms}


@router.get("/export.csv")
async def export_csv(
    intent: Intent = Query(default=Intent.SPEND_SUMMARY),
    group_by: GroupBy = Query(default=GroupBy.COUNTERPARTY),
    metric: Metric = Query(default=Metric.SUM),
    relative: str | None = Query(default=None),
    entity_id: str | None = None,
    counterparty: str | None = None,
    channel: str | None = None,
    transaction_type: str | None = None,
    limit: int = Query(default=1000, ge=1, le=1000),
) -> StreamingResponse:
    """Export the breakdown behind an answer, compiled by compile_plan() like the chat path."""
    _require_ready()
    date_range = None
    try:
        if relative:
            date_range = resolve(DateRange(relative=relative), app_state.ctx.calendar)  # type: ignore[arg-type]
    except Exception as e:  # noqa: BLE001 -- an unknown relative is a client error
        raise HTTPException(400, f"unknown period: {relative}") from None

    try:
        plan = FinanceQueryPlan(
            intent=intent, group_by=group_by, metric=metric, date_range=date_range,
            entity_id=entity_id or app_state.ctx.default_entity, counterparty=counterparty,
            channel=channel, transaction_type=transaction_type, limit=limit)  # type: ignore[arg-type]
        cq = compile_plan(plan)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"invalid export request: {e}") from None

    result = app_state.ch.query(cq.sql, cq.params)
    if not result.rows:
        raise HTTPException(404, "no records match that export request")

    ev = app_state.pipeline().evidence
    if cq.kind == "detail":
        rows = ev._records(plan, cq, result.rows, app_state.ctx.currency)
        for r in rows:
            r.pop("utr", None)
    else:
        rows = [dict(r) for r in result.rows]
        if cq.label_column in {"account_id", "bank_code"}:
            for r in rows:
                r[cq.label_column] = ev._label(cq.label_column, r.get(cq.label_column))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    period = date_range.resolved_label.replace(" ", "-") if date_range else "all-time"
    filename = f"tbx-{intent.value}-{period}.csv"
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})
