"""FinanceQueryPlan -> parameterized MySQL, run live against the source server.

Identifiers come only from the allowlists in this module and every plan-derived
value is a `%(name)s` placeholder the driver escapes. Nothing from the plan is
concatenated into the SQL body; add an allowlist entry instead.

The source `transaction` table has no entity, bank, counterparty or channel column:
entity and bank come from a join onto `account`, counterparty and channel are the
derived expressions in `services/derived_sql.py`. A full account number is never
selected; only its last four digits are.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from ..contracts.enums import GroupBy, Intent, Metric, ReferenceKind
from ..contracts.plan import FinanceQueryPlan
from . import derived_sql as dsql
from . import entity_token

MAX_LIMIT = 1000

_TS = "t.transaction_date"

_GROUP_BY_SQL: dict[GroupBy, tuple[str, str]] = {
    GroupBy.COUNTERPARTY: (dsql.counterparty("t"), "counterparty"),
    GroupBy.ACCOUNT: ("t.account_id", "account_id"),
    GroupBy.BANK: ("a.bank_code", "bank_code"),
    GroupBy.CHANNEL: (dsql.channel("t"), "channel"),
    GroupBy.TRANSACTION_TYPE: ("t.transaction_type", "transaction_type"),
    GroupBy.DAY: (f"DATE({_TS})", "day"),
    GroupBy.WEEK: (f"DATE_SUB(DATE({_TS}), INTERVAL WEEKDAY({_TS}) DAY)", "week"),
    GroupBy.MONTH: (f"DATE_SUB(DATE({_TS}), INTERVAL DAYOFMONTH({_TS}) - 1 DAY)", "month"),
    GroupBy.QUARTER: (f"DATE_ADD(MAKEDATE(YEAR({_TS}), 1), INTERVAL QUARTER({_TS}) - 1 QUARTER)",
                      "quarter"),
    GroupBy.YEAR: (f"MAKEDATE(YEAR({_TS}), 1)", "year"),
}
"""GroupBy -> (sql expression, output label column)."""

TIME_GROUPS = {GroupBy.DAY, GroupBy.WEEK, GroupBy.MONTH, GroupBy.QUARTER, GroupBy.YEAR}

_METRIC_SQL: dict[Metric, str] = {
    Metric.SUM: "SUM({col})",
    Metric.COUNT: "COUNT(*)",
    Metric.AVG: "AVG({col})",
    Metric.MIN: "MIN({col})",
    Metric.MAX: "MAX({col})",
}
"""MEDIAN has no MySQL aggregate and is compiled through a window subquery below."""

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

_FROM = "`transaction` AS t JOIN `account` AS a ON a.account_id = t.account_id"
"""Every transaction query joins its account: that is where entity and bank live."""

TRANSACTION_DETAIL_COLUMNS = [
    "transaction_id", "account_id", "bank_code", "transaction_date", "transaction_type",
    "description", "counterparty", "channel", "transaction_amount",
    "transaction_reference_id", "utr",
]
"""`utr` is the source's plaintext UTR; it is shown only on a detail answer the user
asked for. account_number is never selected from either table."""

_DETAIL_SELECT: dict[str, str] = {
    "transaction_id": "t.transaction_id",
    "account_id": "t.account_id",
    "bank_code": "a.bank_code",
    "transaction_date": "t.transaction_date",
    "transaction_type": "t.transaction_type",
    "description": "t.description",
    "counterparty": dsql.counterparty("t"),
    "channel": dsql.channel("t"),
    "transaction_amount": "t.transaction_amount",
    "transaction_reference_id": "t.transaction_reference_id",
    "utr": "t.utr_number",
}

ACCOUNT_DETAIL_COLUMNS = [
    "account_id", "entity_id", "account_last4", "program_id", "available_balance", "bank_code",
]

_ACCOUNT_SELECT: dict[str, str] = {
    "account_id": "a.account_id",
    "entity_id": "a.entity_id",
    "account_last4": dsql.account_last4("a"),
    "program_id": "a.program_id",
    "available_balance": "a.available_balance",
    "bank_code": "a.bank_code",
}


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

        The UTR is truncated so the panel never carries a searchable identifier, and
        the entity id is masked so the raw id never reaches the browser.
        """
        shown = {}
        for k, v in self.params.items():
            if k == "utr":
                shown[k] = f"{str(v)[:4]}…"
            elif k == "entity_id":
                shown[k] = entity_token.mask(str(v)) or ""
            else:
                shown[k] = str(v)
        return {"sql": self.sql, "params": shown}


def compile_plan(plan: FinanceQueryPlan, *, utr_hash: str | None = None) -> CompiledQuery:
    """Compile a *validated, resolved* plan into parameterized SQL.

    `utr_hash` is accepted for call compatibility and ignored: the live source stores
    the UTR in plaintext, so the lookup binds the value itself.
    """
    table = _INTENT_TABLE[plan.intent]
    params: dict[str, Any] = {}

    if table == "account":
        return _compile_balance(plan, params)

    where = _build_where(plan, params)

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


def _build_where(plan: FinanceQueryPlan, params: dict[str, Any]) -> str:
    """Every value is a placeholder. The counterparty must already be resolved to an
    exact derived value; fuzzy matching lives in the resolver.

    Dates filter the raw timestamp as a half-open range so the source's index on
    transaction_date is used."""
    clauses: list[str] = []

    if plan.entity_id:
        clauses.append("a.entity_id = %(entity_id)s")
        params["entity_id"] = plan.entity_id

    if plan.date_range is not None:
        if not plan.date_range.is_resolved:
            raise CompilationError(
                "date_range reached the compiler unresolved; call services.dates.resolve first"
            )
        clauses.append("t.transaction_date >= %(d_start)s AND t.transaction_date < %(d_end_next)s")
        assert plan.date_range.resolved_end is not None
        params["d_start"] = plan.date_range.resolved_start
        params["d_end_next"] = plan.date_range.resolved_end + timedelta(days=1)

    if plan.counterparty:
        clauses.append(f"{dsql.counterparty('t')} = %(counterparty)s")
        params["counterparty"] = plan.counterparty
    elif plan.counterparty_name:
        raise CompilationError(
            "counterparty_name present but unresolved; the resolver must run before compilation"
        )

    if plan.account_id:
        clauses.append("t.account_id = %(account_id)s")
        params["account_id"] = plan.account_id
    elif plan.account_last4:
        raise CompilationError("account_last4 present but unresolved to an account_id")

    if plan.bank_code:
        clauses.append("a.bank_code = %(bank_code)s")
        params["bank_code"] = plan.bank_code.upper()

    if plan.transaction_type:
        clauses.append("t.transaction_type = %(transaction_type)s")
        params["transaction_type"] = plan.transaction_type.value

    if plan.channel:
        clauses.append(f"{dsql.channel('t')} = %(channel)s")
        params["channel"] = plan.channel.value

    if plan.min_amount is not None:
        clauses.append("t.transaction_amount >= %(min_amount)s")
        params["min_amount"] = plan.min_amount
    if plan.max_amount is not None:
        clauses.append("t.transaction_amount <= %(max_amount)s")
        params["max_amount"] = plan.max_amount

    if plan.reference:
        if plan.reference_kind is ReferenceKind.UTR:
            clauses.append("t.utr_number = %(utr)s")
            params["utr"] = plan.reference.strip()
        else:
            clauses.append("t.transaction_reference_id = %(reference)s")
            params["reference"] = plan.reference.strip()

    return " AND ".join(clauses) if clauses else "1"


def _metric_expr(plan: FinanceQueryPlan) -> str:
    if plan.metric is Metric.MEDIAN:
        raise CompilationError("median is compiled through _median_*")
    return _METRIC_SQL[plan.metric].format(col="t.transaction_amount")


_MEDIAN_PICK = "x.rn IN (FLOOR((x.cnt + 1) / 2), CEIL((x.cnt + 1) / 2))"
"""The middle row, or the two middle rows averaged for an even count."""


def _compile_aggregate(plan, where, params) -> CompiledQuery:
    if plan.metric is Metric.MEDIAN:
        sql = (
            "SELECT AVG(x.v) AS value, MAX(x.cnt) AS record_count, "
            "MAX(x.type_variants) AS type_variants FROM ("
            "SELECT t.transaction_amount AS v, "
            "ROW_NUMBER() OVER (ORDER BY t.transaction_amount) AS rn, "
            "COUNT(*) OVER () AS cnt, "
            "COUNT(DISTINCT t.transaction_type) OVER () AS type_variants "
            f"FROM {_FROM} WHERE {where}) AS x WHERE {_MEDIAN_PICK}"
        )
        return CompiledQuery(sql=sql, params=params, kind="aggregate")
    sql = (
        f"SELECT {_metric_expr(plan)} AS value, COUNT(*) AS record_count, "
        "COUNT(DISTINCT t.transaction_type) AS type_variants "
        f"FROM {_FROM} WHERE {where}"
    )
    return CompiledQuery(sql=sql, params=params, kind="aggregate")


def _compile_grouped(plan, where, params, force_group: GroupBy | None = None) -> CompiledQuery:
    """Time series are ordered chronologically regardless of order_desc."""
    group = force_group or plan.group_by
    if group not in _GROUP_BY_SQL:
        raise CompilationError(f"unsupported group_by: {group}")
    expr, label = _GROUP_BY_SQL[group]
    order = "DESC" if plan.order_desc else "ASC"
    order_by = f"`{label}` ASC" if group in TIME_GROUPS else f"value {order}"
    params["row_limit"] = min(plan.limit, MAX_LIMIT)
    if plan.metric is Metric.MEDIAN:
        sql = (
            f"SELECT x.`{label}` AS `{label}`, AVG(x.v) AS value, MAX(x.cnt) AS record_count FROM ("
            f"SELECT {expr} AS `{label}`, t.transaction_amount AS v, "
            f"ROW_NUMBER() OVER (PARTITION BY {expr} ORDER BY t.transaction_amount) AS rn, "
            f"COUNT(*) OVER (PARTITION BY {expr}) AS cnt "
            f"FROM {_FROM} WHERE {where}) AS x WHERE {_MEDIAN_PICK} "
            f"GROUP BY x.`{label}` ORDER BY {order_by} LIMIT %(row_limit)s"
        )
    else:
        sql = (
            f"SELECT {expr} AS `{label}`, {_metric_expr(plan)} AS value, COUNT(*) AS record_count "
            f"FROM {_FROM} WHERE {where} "
            f"GROUP BY `{label}` ORDER BY {order_by} LIMIT %(row_limit)s"
        )
    return CompiledQuery(sql=sql, params=params, kind="grouped",
                         label_column=label, columns=[label, "value", "record_count"])


def _compile_detail(plan, where, params, *, order: str) -> CompiledQuery:
    cols = TRANSACTION_DETAIL_COLUMNS
    select = ", ".join(f"{_DETAIL_SELECT[c]} AS `{c}`" for c in cols)
    params["row_limit"] = min(plan.limit, MAX_LIMIT)
    sql = (
        f"SELECT {select}, COUNT(*) OVER () AS total_matches "
        f"FROM {_FROM} WHERE {where} "
        f"ORDER BY {order}, t.transaction_id LIMIT %(row_limit)s"
    )
    return CompiledQuery(sql=sql, params=params, kind="detail", columns=cols)


def _compile_balance(plan: FinanceQueryPlan, params: dict[str, Any]) -> CompiledQuery:
    """Balances come from the account table, never from summing transactions."""
    clauses: list[str] = []
    if plan.entity_id:
        clauses.append("a.entity_id = %(entity_id)s")
        params["entity_id"] = plan.entity_id
    if plan.account_id:
        clauses.append("a.account_id = %(account_id)s")
        params["account_id"] = plan.account_id
    elif plan.account_last4:
        raise CompilationError("account_last4 present but unresolved to an account_id")
    if plan.bank_code:
        clauses.append("a.bank_code = %(bank_code)s")
        params["bank_code"] = plan.bank_code.upper()
    where = " AND ".join(clauses) if clauses else "1"
    cols = ACCOUNT_DETAIL_COLUMNS
    select = ", ".join(f"{_ACCOUNT_SELECT[c]} AS `{c}`" for c in cols)
    params["row_limit"] = min(plan.limit, MAX_LIMIT)
    # The totals are window aggregates over every matching account, so the figure the
    # user is given never depends on how many rows the detail list shows.
    sql = (
        f"SELECT {select}, SUM(a.available_balance) OVER () AS balance_total, "
        "COUNT(*) OVER () AS total_matches "
        f"FROM `account` AS a WHERE {where} "
        "ORDER BY a.available_balance DESC LIMIT %(row_limit)s"
    )
    return CompiledQuery(sql=sql, params=params, kind="detail", columns=cols)
