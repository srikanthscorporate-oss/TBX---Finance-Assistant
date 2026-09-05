"""Builds the evidence package: facts, breakdown, sample rows, SQL and parameters.

Fact keys are the composer's placeholder vocabulary. A grouped result cut off by the row
limit is keyed `shown_total`, not `total`, because it is a subtotal.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from ..contracts.enums import Intent, Metric
from ..contracts.evidence import (
    BreakdownRow, ComputedFact, EvidencePackage, SourceRecordRef, VerificationResult,
)
from ..contracts.plan import FinanceQueryPlan
from ..services import composer as comp
from ..services.compiler import CompiledQuery
from .context import DatasetContext, RunContext


def split_result(kind: str, rows: list[dict]) -> tuple[dict | None, list[dict]]:
    """Aggregate queries return one row; everything else returns many."""
    if kind == "aggregate":
        return (rows[0] if rows else {}), []
    return None, rows


def record_count(aggregate: dict | None, rows: list[dict]) -> int:
    if aggregate and aggregate.get("record_count") is not None:
        return int(aggregate["record_count"])
    if rows and all("record_count" in r for r in rows):
        return sum(int(r["record_count"]) for r in rows)
    return len(rows)


class EvidenceBuilder:
    def __init__(self, ctx: DatasetContext):
        self.ctx = ctx

    def build(self, rc: RunContext, plan: FinanceQueryPlan, cq: CompiledQuery,
              result: Any, aggregate: dict | None, rows: list[dict],
              vr: VerificationResult) -> EvidencePackage:
        currency = self.ctx.currency
        if aggregate and aggregate.get("currency"):
            currency = aggregate["currency"]

        count = record_count(aggregate, rows)
        facts = self._facts(plan, cq, aggregate, rows, currency, count)

        return EvidencePackage(
            evidence_id=f"ev_{uuid.uuid4().hex[:12]}",
            run_id=rc.run_id,
            plan_fingerprint=plan.fingerprint(),
            facts=facts,
            breakdown=self._breakdown(cq, rows),
            breakdown_columns=cq.columns,
            sample_records=self._samples(rows),
            total_record_count=count,
            resolved_period=plan.date_range.resolved_label if plan.date_range else None,
            resolved_start=plan.date_range.resolved_start if plan.date_range else None,
            resolved_end=plan.date_range.resolved_end if plan.date_range else None,
            currency=currency,
            entities_resolved={k: v for k, v in {
                "vendor_name": plan.vendor_name,
                "vendor_id": plan.vendor_id,
                "category": plan.category,
            }.items() if v},
            sql=cq.sql,
            sql_params={k: str(v) for k, v in cq.params.items()},
            query_duration_ms=result.duration_ms,
            verification=vr,
            dataset_version=self.ctx.dataset_version)

    def _facts(self, plan, cq, aggregate, rows, currency, count) -> list[ComputedFact]:
        facts: list[ComputedFact] = []

        if aggregate:
            value = float(aggregate.get("value") or 0)
            if plan.intent is Intent.RECONCILIATION_RATE:
                facts.append(ComputedFact(
                    key="rate", value=value, kind="percent",
                    formatted=comp.format_percent(value), record_count=count))
                for k in ("matched", "unmatched"):
                    if k in aggregate:
                        facts.append(ComputedFact(
                            key=k, value=int(aggregate[k]), kind="count",
                            formatted=comp.format_count(aggregate[k])))
            elif plan.metric is Metric.COUNT:
                facts.append(ComputedFact(
                    key="count", value=int(value), kind="count",
                    formatted=comp.format_count(value), record_count=count))
            else:
                facts.append(ComputedFact(
                    key="total", value=value, kind="money", currency=currency,
                    formatted=comp.format_money(value, currency),
                    sql_expression=f"{plan.metric.value}(amount)", record_count=count))

        elif rows and cq.kind == "grouped":
            total = sum(float(r.get("value") or 0) for r in rows)
            truncated = len(rows) >= plan.limit
            facts.append(ComputedFact(
                key="shown_total" if truncated else "total",
                value=total, kind="money", currency=currency,
                formatted=comp.format_money(total, currency), record_count=count))
            top = float(rows[0].get("value") or 0)
            facts.append(ComputedFact(
                key="top_value", value=top, kind="money", currency=currency,
                formatted=comp.format_money(top, currency)))
            facts.append(ComputedFact(
                key="group_count", value=len(rows), kind="count",
                formatted=comp.format_count(len(rows))))

        elif rows:
            facts.append(ComputedFact(
                key="count", value=len(rows), kind="count",
                formatted=comp.format_count(len(rows))))

        facts.append(ComputedFact(
            key="record_count", value=count, kind="count",
            formatted=comp.format_count(count)))
        return facts

    def _breakdown(self, cq: CompiledQuery, rows: list[dict]) -> list[BreakdownRow]:
        if cq.kind != "grouped" or not cq.label_column:
            return []
        total = sum(float(r.get("value") or 0) for r in rows) or 1.0
        name_by_id = {v.vendor_id: v.vendor_name for v in self.ctx.vendors}
        return [
            BreakdownRow(
                label=name_by_id.get(str(r.get(cq.label_column)),
                                     str(r.get(cq.label_column))),
                value=float(r.get("value") or 0),
                record_count=int(r.get("record_count") or 0),
                share_pct=round(100.0 * float(r.get("value") or 0) / total, 2))
            for r in rows
        ]

    @staticmethod
    def _samples(rows: list[dict]) -> list[SourceRecordRef]:
        return [
            SourceRecordRef(
                table="transactions",
                record_id=str(r.get("transaction_id", "")),
                txn_date=date.fromisoformat(r["txn_date"]) if r.get("txn_date") else None,
                vendor_id=r.get("vendor_id"),
                amount=float(r["amount"]) if r.get("amount") else None)
            for r in rows[:25] if "transaction_id" in r
        ]
