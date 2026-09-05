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
    "bill", "bills", "transaction", "transactions", "txn", "txns", "sent", "received",
    "credit", "credits", "credited", "debit", "debits", "debited", "transfer", "transfers",
    "account", "accounts", "balance", "balances", "bank", "banks", "upi", "neft", "imps",
    "rtgs", "cheque", "utr", "ref", "reference", "narration", "statement", "gst", "tax",
    "fee", "fees", "charge", "charges", "refund", "interest", "purchase", "purchases",
    "money", "cash", "rupee", "rupees", "rs", "inr", "lakh", "lakhs", "crore", "trend",
    "breakdown", "compare", "comparison", "top", "largest", "biggest", "highest", "lowest",
    "smallest", "average", "count", "list", "show", "who", "anomaly", "unusual", "report",
    "export", "under", "below", "above", "over", "between", "less", "more", "than",
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
            "how about", "the month before", "by channel", "by account", "by month",
            "by bank", "only the", "just the", "show me those", "list them"}

_WORD = re.compile(r"[a-z][a-z']*")


@dataclass
class Relevance:
    relevant: bool
    signals: list[str]

    @property
    def reason(self) -> str:
        return ("no reference to transactions, counterparties, accounts, amounts, or a period"
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
    for c in ctx.counterparties[:2000]:
        name = c.name.lower()
        first = name.split()[0] if name else ""
        if name and (name in q or (len(first) >= 4 and first in words)):
            signals.append(f"counterparty:{c.name}")
            break
    if re.search(r"\b[A-Z]{4,6}[A-Z0-9]{6,}\b|\b\d{9,}\b", question):
        signals.append("reference")
    if has_previous and any(f in q for f in FOLLOWUP):
        signals.append("follow-up")

    return Relevance(relevant=bool(signals), signals=sorted(set(signals)))
