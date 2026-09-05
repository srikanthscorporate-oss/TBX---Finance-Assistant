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


@router.get("/vendors")
async def vendors() -> list[dict[str, Any]]:
    _require_ready()
    return [
        {"vendor_id": v.vendor_id, "vendor_name": v.vendor_name,
         "category": v.category, "status": v.status}
        for v in app_state.ctx.vendors
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
        "vendor_count": len(ctx.vendors),
        "categories": ctx.categories,
    }


@router.get("/transactions")
async def transactions(
    vendor_id: str | None = None,
    category: str | None = None,
    recon_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    _require_ready()
    plan = FinanceQueryPlan(
        intent=Intent.TRANSACTION_LOOKUP, vendor_id=vendor_id, category=category,
        recon_status=recon_status, limit=limit)  # type: ignore[arg-type]
    cq = compile_plan(plan)
    result = app_state.ch.query(cq.sql, cq.params)
    return {"rows": result.rows, "count": len(result.rows),
            "duration_ms": result.duration_ms}


@router.get("/export.csv")
async def export_csv(
    intent: Intent = Query(default=Intent.TOTAL_SPEND),
    group_by: GroupBy = Query(default=GroupBy.VENDOR),
    metric: Metric = Query(default=Metric.SUM),
    relative: str | None = Query(default=None),
    vendor_id: str | None = None,
    category: str | None = None,
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
            vendor_id=vendor_id, category=category, limit=limit)
        cq = compile_plan(plan)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"invalid export request: {e}") from None

    result = app_state.ch.query(cq.sql, cq.params)
    if not result.rows:
        raise HTTPException(404, "no records match that export request")

    name_by_id = {v.vendor_id: v.vendor_name for v in app_state.ctx.vendors}
    buf = io.StringIO()
    fieldnames = list(result.rows[0].keys())
    if cq.label_column == "vendor_id":
        fieldnames = ["vendor_name"] + fieldnames
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in result.rows:
        out = dict(row)
        if cq.label_column == "vendor_id":
            out["vendor_name"] = name_by_id.get(row.get("vendor_id", ""), "")
        writer.writerow(out)

    period = date_range.resolved_label.replace(" ", "-") if date_range else "all-time"
    filename = f"tbx-{intent.value}-{period}.csv"
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})
