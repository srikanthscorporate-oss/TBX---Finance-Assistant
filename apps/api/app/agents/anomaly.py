"""Counterparty anomaly callout from a median-and-MAD z-score over its prior months.

The history query excludes the period under test. No model call.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from ..db.mysql import MySQLClient, QueryError
from ..services import derived_sql as dsql
from ..services import composer as comp

ANOMALY_TIMEOUT_S = 12
"""Seconds the history query may take before the remark is dropped."""

MIN_HISTORY = 4
Z_THRESHOLD = 2.5


@dataclass
class Anomaly:
    flagged: bool
    ratio: float | None
    z: float | None
    history_months: int
    baseline: float | None
    sentence: str | None


def check(ch: MySQLClient, counterparty: str, entity_id: str | None,
          start, end, current_value: float, currency: str | None) -> Anomaly:
    """A side remark, so it is bounded twice: six months of history before the period,
    and its own short statement timeout. On the live link a slow history query
    simply yields no remark; it can never hold up the answer."""
    fast = MySQLClient(ch.target, timeout=ANOMALY_TIMEOUT_S, max_result_rows=64)
    month = ("DATE_SUB(DATE(t.transaction_date), "
             "INTERVAL DAYOFMONTH(t.transaction_date) - 1 DAY)")
    sql = (f"SELECT {month} AS m, SUM(t.transaction_amount) AS v "
           "FROM `transaction` AS t JOIN `account` AS a ON a.account_id = t.account_id "
           f"WHERE {dsql.counterparty('t')} = %(counterparty)s "
           "AND t.transaction_type = 'debit' AND t.transaction_date < %(start)s "
           "AND t.transaction_date >= DATE_SUB(%(start)s, INTERVAL 6 MONTH)"
           + (" AND a.entity_id = %(entity_id)s" if entity_id else "")
           + " GROUP BY m ORDER BY m")
    params = {"counterparty": counterparty, "start": start}
    if entity_id:
        params["entity_id"] = entity_id
    try:
        rows = fast.query(sql, params).rows
    except QueryError:
        return Anomaly(False, None, None, 0, None, None)
    hist = [float(r["v"]) for r in rows if r.get("v") is not None]
    if len(hist) < MIN_HISTORY:
        return Anomaly(False, None, None, len(hist), None, None)
    med = statistics.median(hist)
    mad = statistics.median([abs(h - med) for h in hist]) or (statistics.pstdev(hist) or 1.0)
    z = 0.6745 * (current_value - med) / mad
    ratio = current_value / med if med else None
    flagged = abs(z) >= Z_THRESHOLD and ratio is not None and (ratio >= 1.8 or ratio <= 0.5)
    sentence = None
    if flagged:
        direction = "higher" if current_value > med else "lower"
        sentence = (f"Unusual for {counterparty}: {comp.format_money(current_value, currency)} is "
                    f"{ratio:.1f}x its typical month of {comp.format_money(med, currency)} "
                    f"over the previous {len(hist)} months ({direction}).")
    return Anomaly(flagged, round(ratio, 2) if ratio else None, round(z, 2), len(hist), med, sentence)
