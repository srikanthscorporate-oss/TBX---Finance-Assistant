"""Anomaly callout: is this vendor's figure unusual against its own history?

Deterministic and cheap: one extra query for the vendor's monthly totals, a
median-and-MAD z-score, insensitive to the outlier being tested, and a sentence only when the
current period stands out. The model never sees or judges the numbers.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass

from ..db.clickhouse import ClickHouseClient, QueryError
from ..services import composer as comp

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


def check(ch: ClickHouseClient, table: str, vendor_id: str, vendor_name: str,
          start, end, current_value: float, currency: str | None) -> Anomaly:
    date_col = "payout_date" if table == "vendor_payouts" else "txn_date"
    sql = (f"SELECT toStartOfMonth({date_col}) AS m, sum(amount) AS v FROM tbx_finance.{table} "
           f"WHERE vendor_id = {{vendor_id:String}} AND {date_col} < {{start:Date}} "
           f"GROUP BY m ORDER BY m")
    try:
        rows = ch.query(sql, {"vendor_id": vendor_id, "start": start}).rows
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
        sentence = (f"Unusual for {vendor_name}: {comp.format_money(current_value, currency)} is "
                    f"{ratio:.1f}x its typical month of {comp.format_money(med, currency)} "
                    f"over the previous {len(hist)} months ({direction}).")
    return Anomaly(flagged, round(ratio, 2) if ratio else None, round(z, 2), len(hist), med, sentence)
