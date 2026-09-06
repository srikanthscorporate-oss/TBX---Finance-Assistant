"""FinanceQueryPlan -> parameterized ClickHouse SQL.

Identifiers come only from the allowlists in this module and every plan-derived
value is a bound ClickHouse parameter. Nothing from the plan is concatenated
into the SQL body; add an allowlist entry instead. Encrypted columns are selected
as ciphertext and decrypted by the evidence builder; the key never enters SQL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from ..contracts.enums import GroupBy, Intent, Metric, ReferenceKind
from ..contracts.plan import FinanceQueryPlan
from . import entity_token
from .active_db import active_db

MAX_LIMIT = 1000

_GROUP_BY_SQL: dict[GroupBy, tuple[str, str]] = {
    GroupBy.COUNTERPARTY: ("t.counterparty", "counterparty"),
    GroupBy.ACCOUNT: ("t.account_id", "account_id"),
    GroupBy.BANK: ("t.bank_code", "bank_code"),
    GroupBy.CHANNEL: ("t.channel", "channel"),
    GroupBy.TRANSACTION_TYPE: ("t.transaction_type", "transaction_type"),
    GroupBy.DAY: ("t.txn_date", "day"),
    GroupBy.WEEK: ("toMonday(t.txn_date)", "week"),
    GroupBy.MONTH: ("toStartOfMonth(t.txn_date)", "month"),
    GroupBy.QUARTER: ("toStartOfQuarter(t.txn_date)", "quarter"),
    GroupBy.YEAR: ("toStartOfYear(t.txn_date)", "year"),
}
"""GroupBy -> (sql expression, output label column)."""

TIME_GROUPS = {GroupBy.DAY, GroupBy.WEEK, GroupBy.MONTH, GroupBy.QUARTER, GroupBy.YEAR}

_METRIC_SQL: dict[Metric, str] = {
    Metric.SUM: "sum({col})",
    Metric.COUNT: "count()",
    Metric.AVG: "avg({col})",
    Metric.MIN: "min({col})",
    Metric.MAX: "max({col})",
    Metric.MEDIAN: "quantileExact(0.5)({col})",
}

_INTENT_TABLE: dict[Intent, str] = {
    Intent.SPEND_SUMMARY: "transaction",
    Intent.COUNTERPARTY_SPEND: "transaction",
    Intent.ACCOUNT_SUMMARY: "transaction",
    Intent.TRANSACTION_LOOKUP: "transaction",
    Intent.REFERENCE_LOOKUP: "transaction",
    Intent.LARGEST_TRANSACTIONS: "transaction",
    Intent.TOP_COUNTERPARTIES: "transaction",
    Intent.CHANNEL_BREAKDOWN: "transaction",
    Intent.PERIOD_COMPARISON: "transaction",
    Intent.TREND: "transaction",
    Intent.ANOMALY_SCAN: "transaction",
    Intent.BALANCE: "account",
    Intent.ACCOUNT_LIST: "account",
}
"""Base table per intent; exhaustive over the closed enum (asserted in tests)."""

TRANSACTION_DETAIL_COLUMNS = [
    "transaction_id", "account_id", "bank_code", "transaction_date", "transaction_type",
    "description", "counterparty", "channel", "transaction_amount",
    "transaction_reference_id", "utr_enc",
]
"""utr_enc is ciphertext; the evidence builder decrypts it. account_number is never
selected from this table because it is not stored here."""

ACCOUNT_DETAIL_COLUMNS = [
    "account_id", "entity_id", "account_last4", "program_id", "available_balance", "bank_code",
]
"""account_number_enc is deliberately absent: a balance answer needs only the last four."""


class CompilationError(ValueError):
    """The plan cannot be compiled; surfaced as an error, never as an answer."""


@dataclass
class CompiledQuery:
    """`kind` is aggregate, grouped or detail."""
    sql: str
    params: dict[str, Any]
    kind: str
    label_column: str | None = None
    value_column: str = "value"
    columns: list[str] = field(default_factory=list)

    def display(self) -> dict[str, Any]:
        """The parameterized SQL and bound parameters for the evidence panel.

        The blind index is truncated so the panel never carries a searchable hash, and the
        entity id is masked so the raw id never reaches the browser.
        """
        shown = {}
        for k, v in self.params.items():
            if k == "utr_hash":
                shown[k] = f"{str(v)[:8]}…"
            elif k == "entity_id":
                shown[k] = entity_token.mask(str(v)) or ""
            else:
                shown[k] = str(v)
        return {"sql": self.sql, "params": shown}


def compile_plan(plan: FinanceQueryPlan, *, utr_hash: str | None = None) -> CompiledQuery:
    """Compile a *validated, resolved* plan into parameterized SQL.

    `utr_hash` is the blind index of the user's UTR, computed by the pipeline; the
    plaintext UTR never becomes a parameter.
    """
    table = _INTENT_TABLE[plan.intent]
    params: dict[str, Any] = {}

    if table == "account":
        return _compile_balance(plan, params)

    where = _build_where(plan, params, utr_hash=utr_hash)

    if plan.intent is Intent.LARGEST_TRANSACTIONS:
        return _compile_detail(plan, where, params, order="t.transaction_amount DESC")
    if plan.intent in {Intent.TRANSACTION_LOOKUP, Intent.REFERENCE_LOOKUP}:
        return _compile_detail(plan, where, params, order="t.transaction_date DESC")
    if plan.intent is Intent.TOP_COUNTERPARTIES:
        return _compile_grouped(plan, where, params, force_group=GroupBy.COUNTERPARTY)
    if plan.intent is Intent.CHANNEL_BREAKDOWN:
        return _compile_grouped(plan, where, params, force_group=GroupBy.CHANNEL)
    if plan.intent is Intent.ACCOUNT_SUMMARY and plan.group_by is GroupBy.NONE:
        return _compile_grouped(plan, where, params, force_group=GroupBy.ACCOUNT)
    if plan.intent is Intent.TREND:
        grain = plan.group_by if plan.group_by in TIME_GROUPS else GroupBy.MONTH
        return _compile_grouped(plan, where, params, force_group=grain)
    if plan.group_by is not GroupBy.NONE:
        return _compile_grouped(plan, where, params)
    return _compile_aggregate(plan, where, params)


def _build_where(plan: FinanceQueryPlan, params: dict[str, Any], *,
                 utr_hash: str | None) -> str:
    """Every value is a bound parameter. The counterparty must already be resolved to
    an exact stored value; fuzzy matching lives in the resolver.

    Dates filter the raw transaction_date as a half-open range rather than the
    materialised txn_date, because only the raw column prunes monthly partitions."""
    clauses: list[str] = []

    if plan.entity_id:
        clauses.append("t.entity_id = {entity_id:String}")
        params["entity_id"] = plan.entity_id

    if plan.date_range is not None:
        if not plan.date_range.is_resolved:
            raise CompilationError(
                "date_range reached the compiler unresolved; call services.dates.resolve first"
            )
        clauses.append("t.transaction_date >= toDateTime64({d_start:Date}, 6) "
                       "AND t.transaction_date < toDateTime64({d_end_next:Date}, 6)")
        assert plan.date_range.resolved_end is not None
        params["d_start"] = plan.date_range.resolved_start
        params["d_end_next"] = plan.date_range.resolved_end + timedelta(days=1)

    if plan.counterparty:
        clauses.append("t.counterparty = {counterparty:String}")
        params["counterparty"] = plan.counterparty
    elif plan.counterparty_name:
        raise CompilationError(
            "counterparty_name present but unresolved; the resolver must run before compilation"
        )

    if plan.account_id:
        clauses.append("t.account_id = {account_id:String}")
        params["account_id"] = plan.account_id
    elif plan.account_last4:
        raise CompilationError("account_last4 present but unresolved to an account_id")

    if plan.bank_code:
        clauses.append("t.bank_code = {bank_code:String}")
        params["bank_code"] = plan.bank_code.upper()

    if plan.transaction_type:
        clauses.append("t.transaction_type = {transaction_type:String}")
        params["transaction_type"] = plan.transaction_type.value

    if plan.channel:
        clauses.append("t.channel = {channel:String}")
        params["channel"] = plan.channel.value

    if plan.min_amount is not None:
        clauses.append("t.transaction_amount >= {min_amount:Decimal64(2)}")
        params["min_amount"] = plan.min_amount
    if plan.max_amount is not None:
        clauses.append("t.transaction_amount <= {max_amount:Decimal64(2)}")
        params["max_amount"] = plan.max_amount

    if plan.reference:
        if plan.reference_kind is ReferenceKind.UTR:
            if not utr_hash:
                raise CompilationError("UTR lookup requires the blind index from the pipeline")
            clauses.append("t.utr_hash = {utr_hash:String}")
            params["utr_hash"] = utr_hash
        else:
            clauses.append("t.transaction_reference_id = {reference:String}")
            params["reference"] = plan.reference.strip()

    return " AND ".join(clauses) if clauses else "1"


def _metric_expr(plan: FinanceQueryPlan) -> str:
    return _METRIC_SQL[plan.metric].format(col="t.transaction_amount")


def _compile_aggregate(plan, where, params) -> CompiledQuery:
    sql = (
        f"SELECT {_metric_expr(plan)} AS value, count() AS record_count, "
        "uniqExact(t.transaction_type) AS type_variants "
        f"FROM {active_db()}.transaction AS t WHERE {where}"
    )
    return CompiledQuery(sql=sql, params=params, kind="aggregate")


def _compile_grouped(plan, where, params, force_group: GroupBy | None = None) -> CompiledQuery:
    """Time series are ordered chronologically regardless of order_desc."""
    group = force_group or plan.group_by
    if group not in _GROUP_BY_SQL:
        raise CompilationError(f"unsupported group_by: {group}")
    expr, label = _GROUP_BY_SQL[group]
    order = "DESC" if plan.order_desc else "ASC"
    order_by = f"{label} ASC" if group in TIME_GROUPS else f"value {order}"
    params["row_limit"] = min(plan.limit, MAX_LIMIT)
    sql = (
        f"SELECT {expr} AS {label}, {_metric_expr(plan)} AS value, count() AS record_count "
        f"FROM {active_db()}.transaction AS t WHERE {where} "
        f"GROUP BY {label} ORDER BY {order_by} LIMIT {{row_limit:UInt32}}"
    )
    return CompiledQuery(sql=sql, params=params, kind="grouped",
                         label_column=label, columns=[label, "value", "record_count"])


def _compile_detail(plan, where, params, *, order: str) -> CompiledQuery:
    cols = TRANSACTION_DETAIL_COLUMNS
    select = ", ".join(f"t.{c} AS {c}" for c in cols)
    params["row_limit"] = min(plan.limit, MAX_LIMIT)
    sql = (
        f"SELECT {select}, count() OVER () AS total_matches "
        f"FROM {active_db()}.transaction AS t WHERE {where} "
        f"ORDER BY {order}, t.transaction_id LIMIT {{row_limit:UInt32}}"
    )
    return CompiledQuery(sql=sql, params=params, kind="detail", columns=cols)


def _compile_balance(plan: FinanceQueryPlan, params: dict[str, Any]) -> CompiledQuery:
    """Balances come from the account table, never from summing transactions."""
    clauses: list[str] = []
    if plan.entity_id:
        clauses.append("a.entity_id = {entity_id:String}")
        params["entity_id"] = plan.entity_id
    if plan.account_id:
        clauses.append("a.account_id = {account_id:String}")
        params["account_id"] = plan.account_id
    elif plan.account_last4:
        raise CompilationError("account_last4 present but unresolved to an account_id")
    if plan.bank_code:
        clauses.append("a.bank_code = {bank_code:String}")
        params["bank_code"] = plan.bank_code.upper()
    where = " AND ".join(clauses) if clauses else "1"
    cols = ACCOUNT_DETAIL_COLUMNS
    select = ", ".join(f"a.{c} AS {c}" for c in cols)
    params["row_limit"] = min(plan.limit, MAX_LIMIT)
    sql = (
        f"SELECT {select} FROM {active_db()}.account AS a FINAL WHERE {where} "
        "ORDER BY a.available_balance DESC LIMIT {row_limit:UInt32}"
    )
    return CompiledQuery(sql=sql, params=params, kind="detail", columns=cols)
