"""Token-free relevance gate run before any agent.

One signal (money word, period word, vendor or category name, currency symbol or number)
is enough to pass; the planner remains the second gate.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .context import DatasetContext

MONEY = {
    "spend", "spent", "spending", "cost", "costs", "pay", "paid", "payment", "payments",
    "payout", "payouts", "expense", "expenses", "amount", "total", "totals", "sum",
    "invoice", "invoices", "bill", "bills", "vendor", "vendors", "supplier", "suppliers",
    "transaction", "transactions", "reconcile", "reconciled", "reconciliation",
    "unreconciled", "unmatched", "matched", "disputed", "pending", "category",
    "categories", "account", "accounts", "ledger", "outstanding", "balance", "revenue",
    "budget", "gst", "tax", "vat", "fee", "fees", "charge", "charges", "refund",
    "purchase", "purchases", "procurement", "spent", "money", "cash", "rupee", "rupees",
    "dollar", "dollars", "inr", "usd", "trend", "breakdown", "compare", "comparison",
    "top", "largest", "biggest", "highest", "lowest", "average", "count", "how many",
    "how much", "anomaly", "unusual", "report", "export",
}
PERIOD = {
    "month", "months", "monthly", "quarter", "quarters", "quarterly", "year", "years",
    "yearly", "week", "weeks", "weekly", "day", "days", "daily", "today", "yesterday",
    "last", "this", "previous", "before", "ago", "since", "between", "period",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "jan", "feb", "mar", "apr",
    "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec", "q1", "q2", "q3", "q4",
}
FOLLOWUP = {"what about", "and for", "break that", "break it", "same for", "compare that",
            "how about", "the month before", "by category", "by vendor", "by month"}

_WORD = re.compile(r"[a-z][a-z']*")


@dataclass
class Relevance:
    relevant: bool
    signals: list[str]

    @property
    def reason(self) -> str:
        return ("no reference to spend, vendors, payouts, reconciliation, or a period"
                if not self.relevant else ", ".join(self.signals[:4]))


def assess(question: str, ctx: DatasetContext, has_previous: bool) -> Relevance:
    q = question.lower().strip()
    words = set(_WORD.findall(q))
    signals: list[str] = []

    for w in words & MONEY:
        signals.append(w)
    for phrase in ("how much", "how many"):
        if phrase in q:
            signals.append(phrase)
    if words & PERIOD:
        signals.append("period")
    if re.search(r"[₹$€£]|\b\d{2,}\b", q):
        signals.append("figure")
    for v in ctx.vendors:
        name = v.vendor_name.lower()
        first = name.split()[0]
        if name in q or (len(first) >= 4 and first in words):
            signals.append(f"vendor:{v.vendor_name}")
            break
    for c in ctx.categories:
        if c.lower() in q:
            signals.append(f"category:{c}")
            break
    if has_previous and any(f in q for f in FOLLOWUP):
        signals.append("follow-up")

    return Relevance(relevant=bool(signals), signals=sorted(set(signals)))
