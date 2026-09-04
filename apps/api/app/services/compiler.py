"""FinanceQueryPlan -> parameterized ClickHouse SQL.

Security model, in order of the layers a malicious or malformed plan must pass:

  1. Pydantic closed enums     -- an unknown intent/metric/group_by never parses.
  2. This module's allowlists  -- identifiers are looked up in dicts defined
                                  here; nothing from the plan is ever
                                  interpolated into SQL as an identifier.
  3. Bound parameters          -- every user-influenced VALUE travels as a
                                  ClickHouse query parameter, never as text.
  4. Read-only DB credentials  -- see infra/clickhouse/002_readonly_user.sql.

There is deliberately no code path that concatenates plan-derived strings into
the SQL body. If you find yourself needing one, add an allowlist entry instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..contracts.enums import Direction, GroupBy, Intent, Metric, ReconStatus, TxnStatus
from ..contracts.plan import FinanceQueryPlan

DB = "tbx_finance"
MAX_LIMIT = 1000

# --- Allowlists -----------------------------------------------------------
# Every identifier that can appear in generated SQL is a VALUE in one of these
# maps. Plan fields select a key; they never supply the identifier itself.

_GROUP_BY_SQL: dict[GroupBy, tuple[str, str]] = {
    # GroupBy -> (sql expression, output label column)
    GroupBy.VENDOR: ("t.vendor_id", "vendor_id"),
    GroupBy.CATEGORY: ("t.category", "category"),
    GroupBy.ACCOUNT: ("t.account_code", "account_code"),
    GroupBy.STATUS: ("t.status", "status"),
    GroupBy.RECON_STATUS: ("t.reconciliation_status", "reconciliation_status"),
    GroupBy.PAYMENT_METHOD: ("t.payment_method", "payment_method"),
    GroupBy.DAY: ("toDate(t.txn_date)", "day"),
    GroupBy.WEEK: ("toMonday(t.txn_date)", "week"),
    GroupBy.MONTH: ("toStartOfMonth(t.txn_date)", "month"),
    GroupBy.QUARTER: ("toStartOfQuarter(t.txn_date)", "quarter"),
    GroupBy.YEAR: ("toStartOfYear(t.txn_date)", "year"),
}

_METRIC_SQL: dict[Metric, str] = {
    Metric.SUM: "sum({col})",
    Metric.COUNT: "count()",
    Metric.AVG: "avg({col})",
    Metric.MIN: "min({col})",
    Metric.MAX: "max({col})",
    Metric.MEDIAN: "quantileExact(0.5)({col})",
}

# Which base table each intent reads. Intents are a closed enum, so this map is
# exhaustive by construction (asserted in tests).
_INTENT_TABLE: dict[Intent, str] = {
    Intent.TOTAL_SPEND: "transactions",
    Intent.VENDOR_SPEND: "transactions",
    Intent.CATEGORY_SPEND: "transactions",
    Intent.ACCOUNT_SPEND: "transactions",
    Intent.TRANSACTION_LOOKUP: "transactions",
    Intent.UNRECONCILED: "transactions",
    Intent.RECONCILIATION_RATE: "transactions",
    Intent.RECONCILIATION_SUMMARY: "transactions",
    Intent.PERIOD_COMPARISON: "transactions",
    Intent.TOP_VENDORS: "transactions",
    Intent.TREND: "transactions",
    Intent.ANOMALY_SCAN: "transactions",
    Intent.VENDOR_PAYOUTS: "vendor_payouts",
    Intent.PAYOUT_STATUS: "vendor_payouts",
    Intent.VENDOR_LOOKUP: "vendors",
}

# Detail columns returned for record-level lookups, per table.
_DETAIL_COLUMNS: dict[str, list[str]] = {
    "transactions": [
        "transaction_id", "txn_date", "vendor_id", "account_code", "category",
        "description", "amount", "currency", "direction", "status",
        "payment_method", "reconciliation_status", "invoice_ref",
    ],
    "vendor_payouts": [
        "payout_id", "payout_date", "vendor_id", "amount", "currency",
        "status", "method", "invoice_count", "reference",
    ],
    "vendors": [
        "vendor_id", "vendor_name", "legal_name", "category", "status",
        "country", "currency", "onboarded_at",
    ],
}

_DATE_COLUMN: dict[str, str] = {
    "transactions": "txn_date",
    "vendor_payouts": "payout_date",
    "vendors": "onboarded_at",
}

_AMOUNT_COLUMN: dict[str, str] = {
    "transactions": "amount",
    "vendor_payouts": "amount",
    "vendors": "",
}


class CompilationError(ValueError):
    """The plan cannot be compiled. Surfaced as an internal error, never as an
    answer -- we do not guess at what the user meant."""


@dataclass
class CompiledQuery:
    sql: str
    params: dict[str, Any]
    kind: str                       # aggregate | grouped | detail
    label_column: str | None = None
    value_column: str = "value"
    columns: list[str] = field(default_factory=list)

    def display(self) -> dict[str, Any]:
        """What the evidence panel shows: the parameterized SQL and the bound
        parameters, side by side. We deliberately do NOT render an "inlined"
        SQL string -- showing users a copy-pasteable concatenated query would
        model exactly the pattern this compiler exists to prevent."""
        return {"sql": self.sql, "params": {k: str(v) for k, v in self.params.items()}}


def compile_plan(plan: FinanceQueryPlan) -> CompiledQuery:
    """Compile a *validated, date-resolved* plan into parameterized SQL."""
    table = _INTENT_TABLE[plan.intent]
    params: dict[str, Any] = {}
    where = _build_where(plan, table, params)

    if plan.intent is Intent.RECONCILIATION_RATE:
        return _compile_recon_rate(plan, where, params)
    if plan.intent in {Intent.TRANSACTION_LOOKUP, Intent.UNRECONCILED, Intent.VENDOR_LOOKUP}:
        return _compile_detail(plan, table, where, params)
    if plan.intent is Intent.TOP_VENDORS:
        return _compile_grouped(plan, table, where, params, force_group=GroupBy.VENDOR)
    if plan.intent is Intent.TREND:
        grain = plan.group_by if plan.group_by in {
            GroupBy.DAY, GroupBy.WEEK, GroupBy.MONTH, GroupBy.QUARTER, GroupBy.YEAR
        } else GroupBy.MONTH
        return _compile_grouped(plan, table, where, params, force_group=grain)
    if plan.group_by is not GroupBy.NONE:
        return _compile_grouped(plan, table, where, params)
    return _compile_aggregate(plan, table, where, params)


# --- WHERE ----------------------------------------------------------------

def _build_where(plan: FinanceQueryPlan, table: str, params: dict[str, Any]) -> str:
    clauses: list[str] = []
    date_col = _DATE_COLUMN[table]

    if plan.date_range is not None:
        if not plan.date_range.is_resolved:
            raise CompilationError(
                "date_range reached the compiler unresolved; call services.dates.resolve first"
            )
        clauses.append(f"t.{date_col} >= {{d_start:Date}} AND t.{date_col} <= {{d_end:Date}}")
        params["d_start"] = plan.date_range.resolved_start
        params["d_end"] = plan.date_range.resolved_end

    if plan.vendor_id:
        clauses.append("t.vendor_id = {vendor_id:String}")
        params["vendor_id"] = plan.vendor_id
    elif plan.vendor_name and table == "vendors":
        # Only the vendor-lookup path matches on name, and only as an exact
        # bound parameter. Fuzzy matching happens in the resolver, not in SQL.
        clauses.append("t.vendor_name = {vendor_name:String}")
        params["vendor_name"] = plan.vendor_name
    elif plan.vendor_name and not plan.vendor_id:
        raise CompilationError(
            "vendor_name present but unresolved; the vendor resolver must run before compilation"
        )

    if plan.category:
        clauses.append("t.category = {category:String}")
        params["category"] = plan.category

    if plan.account_code and table == "transactions":
        clauses.append("t.account_code = {account_code:String}")
        params["account_code"] = plan.account_code

    if plan.txn_status and table in {"transactions", "vendor_payouts"}:
        clauses.append("t.status = {txn_status:String}")
        params["txn_status"] = plan.txn_status.value

    if plan.recon_status and table == "transactions":
        clauses.append("t.reconciliation_status = {recon_status:String}")
        params["recon_status"] = plan.recon_status.value

    if plan.direction and table == "transactions":
        clauses.append("t.direction = {direction:String}")
        params["direction"] = plan.direction.value

    if plan.currency:
        clauses.append("t.currency = {currency:String}")
        params["currency"] = plan.currency.upper()

    amount_col = _AMOUNT_COLUMN[table]
    if amount_col and plan.min_amount is not None:
        clauses.append(f"t.{amount_col} >= {{min_amount:Decimal64(2)}}")
        params["min_amount"] = plan.min_amount
    if amount_col and plan.max_amount is not None:
        clauses.append(f"t.{amount_col} <= {{max_amount:Decimal64(2)}}")
        params["max_amount"] = plan.max_amount

    # `unreconciled` is a named intent, not a free-text filter.
    if plan.intent is Intent.UNRECONCILED and plan.recon_status is None:
        clauses.append("t.reconciliation_status IN ('unmatched', 'pending', 'disputed')")

    return " AND ".join(clauses) if clauses else "1"


# --- Shapes ---------------------------------------------------------------

def _metric_expr(plan: FinanceQueryPlan, table: str) -> str:
    amount_col = _AMOUNT_COLUMN[table]
    if plan.metric is not Metric.COUNT and not amount_col:
        raise CompilationError(f"metric {plan.metric.value} is not available on {table}")
    return _METRIC_SQL[plan.metric].format(col=f"t.{amount_col}")


def _compile_aggregate(plan, table, where, params) -> CompiledQuery:
    metric = _metric_expr(plan, table)
    sql = (
        f"SELECT {metric} AS value, count() AS record_count, "
        f"any(t.currency) AS currency, uniqExact(t.currency) AS currency_variants "
        f"FROM {DB}.{table} AS t WHERE {where}"
    ) if table != "vendors" else (
        f"SELECT count() AS value, count() AS record_count FROM {DB}.{table} AS t WHERE {where}"
    )
    return CompiledQuery(sql=sql, params=params, kind="aggregate")


def _compile_grouped(plan, table, where, params, force_group: GroupBy | None = None) -> CompiledQuery:
    group = force_group or plan.group_by
    if group not in _GROUP_BY_SQL:
        raise CompilationError(f"unsupported group_by: {group}")
    expr, label = _GROUP_BY_SQL[group]
    metric = _metric_expr(plan, table)
    order = "DESC" if plan.order_desc else "ASC"
    # Time series read chronologically regardless of order_desc.
    if group in {GroupBy.DAY, GroupBy.WEEK, GroupBy.MONTH, GroupBy.QUARTER, GroupBy.YEAR}:
        order_by = f"{label} ASC"
    else:
        order_by = f"value {order}"

    params["row_limit"] = min(plan.limit, MAX_LIMIT)
    sql = (
        f"SELECT {expr} AS {label}, {metric} AS value, count() AS record_count "
        f"FROM {DB}.{table} AS t WHERE {where} "
        f"GROUP BY {label} ORDER BY {order_by} LIMIT {{row_limit:UInt32}}"
    )
    return CompiledQuery(sql=sql, params=params, kind="grouped",
                         label_column=label, columns=[label, "value", "record_count"])


def _compile_detail(plan, table, where, params) -> CompiledQuery:
    cols = _DETAIL_COLUMNS[table]
    select = ", ".join(f"t.{c} AS {c}" for c in cols)
    date_col = _DATE_COLUMN[table]
    params["row_limit"] = min(plan.limit, MAX_LIMIT)
    sql = (
        f"SELECT {select} FROM {DB}.{table} AS t WHERE {where} "
        f"ORDER BY t.{date_col} DESC LIMIT {{row_limit:UInt32}}"
    )
    return CompiledQuery(sql=sql, params=params, kind="detail", columns=cols)


def _compile_recon_rate(plan, where, params) -> CompiledQuery:
    sql = (
        "SELECT "
        "countIf(t.reconciliation_status = 'matched') AS matched, "
        "countIf(t.reconciliation_status != 'matched') AS unmatched, "
        "count() AS record_count, "
        "if(count() = 0, 0, round(100.0 * countIf(t.reconciliation_status = 'matched') / count(), 2)) AS value "
        f"FROM {DB}.transactions AS t WHERE {where}"
    )
    return CompiledQuery(sql=sql, params=params, kind="aggregate")
