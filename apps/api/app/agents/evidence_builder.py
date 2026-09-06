"""Builds the evidence package: facts, breakdown, sample rows, SQL and parameters.

Fact keys are the composer's placeholder vocabulary. A grouped result cut off by the row
limit is keyed `shown_total`, not `total`, because it is a subtotal.
"""
from __future__ import annotations

import re
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
from ..services import entity_token
from ..services.crypto import FieldCipher
from .context import DatasetContext, RunContext

RECORD_COLUMNS = ["transaction_date", "transaction_type", "amount_formatted", "counterparty",
                  "channel", "account", "bank", "reference", "utr", "description", "transaction_id"]
"""What a detail answer shows. `account` is masked; `utr` is decrypted here and only here."""

ACCOUNT_COLUMNS = ["account", "bank", "program_id", "available_balance_formatted", "account_id"]

_LONG_DIGITS = re.compile(r"\d{10,}")


def mask_narration(text: str) -> str:
    """Bank narrations embed the counterparty's or the customer's own account number; any
    run of ten or more digits is shown as its last four so a full number never leaves."""
    return _LONG_DIGITS.sub(lambda m: "X" * (len(m.group()) - 4) + m.group()[-4:], text)


def split_result(kind: str, rows: list[dict]) -> tuple[dict | None, list[dict]]:
    """Aggregate queries return one row; everything else returns many."""
    if kind == "aggregate":
        return (rows[0] if rows else {}), []
    return None, rows


def record_count(aggregate: dict | None, rows: list[dict]) -> int:
    if aggregate and aggregate.get("record_count") is not None:
        return int(aggregate["record_count"])
    if rows and rows[0].get("total_matches") is not None:
        return int(rows[0]["total_matches"])
    if rows and all("record_count" in r for r in rows):
        return sum(int(r["record_count"]) for r in rows)
    return len(rows)


class EvidenceBuilder:
    def __init__(self, ctx: DatasetContext, cipher: FieldCipher | None = None):
        self.ctx = ctx
        self.cipher = cipher
        self._acct = {a.account_id: a for a in ctx.accounts}

    def build(self, rc: RunContext, plan: FinanceQueryPlan, cq: CompiledQuery,
              result: Any, aggregate: dict | None, rows: list[dict],
              vr: VerificationResult) -> EvidencePackage:
        currency = self.ctx.currency
        count = record_count(aggregate, rows)
        records = self._records(plan, cq, rows, currency) if cq.kind == "detail" else []
        facts = self._facts(plan, cq, aggregate, rows, currency, count, records)

        return EvidencePackage(
            evidence_id=f"ev_{uuid.uuid4().hex[:12]}",
            run_id=rc.run_id,
            plan_fingerprint=plan.fingerprint(),
            facts=facts,
            breakdown=self._breakdown(cq, rows),
            breakdown_columns=cq.columns,
            sample_records=self._samples(rows),
            records=records,
            record_columns=(ACCOUNT_COLUMNS
                            if cq.kind == "detail"
                            and plan.intent in {Intent.BALANCE, Intent.ACCOUNT_LIST}
                            else RECORD_COLUMNS) if records else [],
            total_record_count=count,
            resolved_period=plan.date_range.resolved_label if plan.date_range else None,
            resolved_start=plan.date_range.resolved_start if plan.date_range else None,
            resolved_end=plan.date_range.resolved_end if plan.date_range else None,
            currency=currency,
            entities_resolved={k: v for k, v in {
                "counterparty": plan.counterparty,
                "account": self._acct[plan.account_id].masked if plan.account_id in self._acct else None,
                "bank": plan.bank_code,
                "channel": plan.channel.value if plan.channel else None,
                "transaction_type": plan.transaction_type.value if plan.transaction_type else None,
                "reference": plan.reference,
                "reference_kind": plan.reference_kind.value if plan.reference_kind else None,
                "entity_id": entity_token.mask(plan.entity_id),
            }.items() if v},
            sql=cq.sql,
            sql_params=cq.display()["params"],
            query_duration_ms=result.duration_ms,
            verification=vr,
            dataset_version=self.ctx.dataset_version)

    def _facts(self, plan, cq, aggregate, rows, currency, count, records) -> list[ComputedFact]:
        facts: list[ComputedFact] = []

        if aggregate:
            value = float(aggregate.get("value") or 0)
            if plan.metric is Metric.COUNT:
                facts.append(ComputedFact(
                    key="count", value=int(value), kind="count",
                    formatted=comp.format_count(value), record_count=count))
            else:
                facts.append(ComputedFact(
                    key="total", value=value, kind="money", currency=currency,
                    formatted=comp.format_money(value, currency),
                    sql_expression=f"{plan.metric.value}(transaction_amount)",
                    record_count=count))
        elif rows and cq.kind == "grouped":
            total = sum(float(r.get("value") or 0) for r in rows)
            truncated = len(rows) >= plan.limit
            money = plan.metric is not Metric.COUNT
            facts.append(ComputedFact(
                key="shown_total" if truncated else "total",
                value=total, kind="money" if money else "count", currency=currency if money else None,
                formatted=comp.format_money(total, currency) if money else comp.format_count(total),
                record_count=count))
            top = float(rows[0].get("value") or 0)
            facts.append(ComputedFact(
                key="top_value", value=top, kind="money" if money else "count",
                currency=currency if money else None,
                formatted=comp.format_money(top, currency) if money else comp.format_count(top)))
            facts.append(ComputedFact(
                key="top_label", value=self._label(cq.label_column, rows[0].get(cq.label_column)),
                kind="text",
                formatted=self._label(cq.label_column, rows[0].get(cq.label_column))))
            facts.append(ComputedFact(
                key="group_count", value=len(rows), kind="count",
                formatted=comp.format_count(len(rows))))
        elif rows and plan.intent is Intent.ACCOUNT_LIST:
            facts.append(ComputedFact(
                key="count", value=len(rows), kind="count",
                formatted=comp.format_count(len(rows))))
            facts.append(ComputedFact(
                key="bank_count", value=len({r.get("bank_code") for r in rows}), kind="count",
                formatted=comp.format_count(len({r.get("bank_code") for r in rows}))))
        elif rows and plan.intent is Intent.BALANCE:
            total = sum(float(r.get("available_balance") or 0) for r in rows)
            facts.append(ComputedFact(
                key="balance_total", value=total, kind="money", currency=currency,
                formatted=comp.format_money(total, currency), record_count=len(rows)))
            facts.append(ComputedFact(
                key="count", value=len(rows), kind="count",
                formatted=comp.format_count(len(rows))))
        elif rows:
            facts.append(ComputedFact(
                key="count", value=count, kind="count",
                formatted=comp.format_count(count)))
            total = sum(float(r.get("transaction_amount") or 0) for r in rows)
            facts.append(ComputedFact(
                key="shown_total" if count > len(rows) else "total",
                value=total, kind="money", currency=currency,
                formatted=comp.format_money(total, currency), record_count=len(rows)))
            if count > len(rows):
                facts.append(ComputedFact(
                    key="shown_count", value=len(rows), kind="count",
                    formatted=comp.format_count(len(rows))))
            if len(rows) == 1 and records:
                r0 = records[0]
                facts.append(ComputedFact(
                    key="amount", value=total, kind="money", currency=currency,
                    formatted=comp.format_money(total, currency)))
                facts.append(ComputedFact(
                    key="txn_date", value=r0["transaction_date"], kind="date",
                    formatted=r0["transaction_date"]))
                facts.append(ComputedFact(
                    key="counterparty", value=r0["counterparty"] or "unnamed", kind="text",
                    formatted=r0["counterparty"] or "an unnamed counterparty"))
                facts.append(ComputedFact(
                    key="channel", value=r0["channel"], kind="text", formatted=r0["channel"]))
                facts.append(ComputedFact(
                    key="account", value=r0["account"], kind="text", formatted=r0["account"]))
                facts.append(ComputedFact(
                    key="txn_type", value=r0["transaction_type"], kind="text",
                    formatted=r0["transaction_type"]))

        facts.append(ComputedFact(
            key="record_count", value=count, kind="count",
            formatted=comp.format_count(count)))
        return facts

    def _breakdown(self, cq: CompiledQuery, rows: list[dict]) -> list[BreakdownRow]:
        if cq.kind != "grouped" or not cq.label_column:
            return []
        total = sum(float(r.get("value") or 0) for r in rows) or 1.0
        return [
            BreakdownRow(
                label=self._label(cq.label_column, r.get(cq.label_column)),
                value=float(r.get("value") or 0),
                record_count=int(r.get("record_count") or 0),
                share_pct=round(100.0 * float(r.get("value") or 0) / total, 2))
            for r in rows
        ]

    def _label(self, column: str, raw: Any) -> str:
        v = str(raw)
        if column == "account_id":
            a = self._acct.get(v)
            return f"{a.masked} ({a.bank_code})" if a else v
        if column == "bank_code":
            return self.ctx.banks.get(v, v)
        if column == "counterparty" and not v:
            return "(unnamed)"
        return v

    def _records(self, plan, cq, rows, currency) -> list[dict[str, Any]]:
        """Detail rows for display. Account numbers are shown masked from the stored last
        four; UTRs are decrypted here because the user asked for that transaction."""
        out: list[dict[str, Any]] = []
        for r in rows:
            if plan.intent in {Intent.BALANCE, Intent.ACCOUNT_LIST}:
                a = self._acct.get(str(r.get("account_id")))
                out.append({
                    "account": a.masked if a else f"XXXXXX{r.get('account_last4', '')}",
                    "bank": self.ctx.banks.get(str(r.get("bank_code")), str(r.get("bank_code"))),
                    "program_id": int(r.get("program_id") or 0),
                    "available_balance_formatted": comp.format_money(
                        float(r.get("available_balance") or 0), currency),
                    "account_id": str(r.get("account_id")),
                })
                continue
            a = self._acct.get(str(r.get("account_id")))
            utr = ""
            if r.get("utr_enc") and self.cipher is not None:
                try:
                    utr = self.cipher.decrypt(str(r["utr_enc"]))
                except ValueError:
                    utr = "(undecryptable)"
            elif r.get("utr_enc"):
                utr = "(encrypted)"
            ts = str(r.get("transaction_date", ""))
            out.append({
                "transaction_date": ts[:19],
                "transaction_type": str(r.get("transaction_type", "")),
                "amount_formatted": comp.format_money(float(r.get("transaction_amount") or 0), currency),
                "amount": float(r.get("transaction_amount") or 0),
                "counterparty": str(r.get("counterparty") or ""),
                "channel": str(r.get("channel") or ""),
                "account": a.masked if a else "XXXXXX????",
                "bank": self.ctx.banks.get(str(r.get("bank_code")), str(r.get("bank_code"))),
                "reference": str(r.get("transaction_reference_id") or ""),
                "utr": utr,
                "description": mask_narration(str(r.get("description") or "")),
                "transaction_id": str(r.get("transaction_id", "")),
            })
        return out

    @staticmethod
    def _samples(rows: list[dict]) -> list[SourceRecordRef]:
        out = []
        for r in rows[:25]:
            if "transaction_id" not in r:
                continue
            ts = str(r.get("transaction_date", ""))[:10]
            out.append(SourceRecordRef(
                table="transaction",
                record_id=str(r.get("transaction_id", "")),
                txn_date=date.fromisoformat(ts) if ts else None,
                counterparty=r.get("counterparty"),
                amount=float(r["transaction_amount"]) if r.get("transaction_amount") else None))
        return out
