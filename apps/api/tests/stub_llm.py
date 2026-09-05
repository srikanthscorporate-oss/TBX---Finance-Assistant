"""Deterministic stand-in for the LLM, wired in only by tests and the offline demo.

It recognises a fixed set of phrasings over the bank schema and is not a production
fallback.
"""
from __future__ import annotations

import json
import re


def _plan(**kw) -> str:
    return json.dumps({"scope": "in_scope", "plan": kw})


def stub_completion(*, model: str, messages: list[dict], **kwargs):
    system = messages[0]["content"]
    user = messages[-1]["content"]
    is_compose = "you must NOT write any number" in system
    is_delta = "FOLLOW-UP question" in system
    if is_compose:
        content = _compose_draft(system)
    elif is_delta:
        content = _delta(system, user)
    else:
        content = _scope_and_plan(user)
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": len(system + user) // 4,
                  "completion_tokens": len(content) // 4},
    }


def _compose_draft(system: str) -> str:
    """Draft prose using only the placeholders the prompt advertises."""
    line = ""
    for ln in system.splitlines():
        if ln.strip().startswith("{{") and "}}," in ln or (
                ln.strip().startswith("{{") and ln.strip().endswith("}}")):
            line = ln
            break
    allowed = set(re.findall(r"\{\{([a-z][a-z0-9_.]*)\}\}", line))
    if "amount" in allowed and "counterparty" in allowed:
        return ("That is a payment of {{amount}} to {{counterparty}} on {{txn_date}} "
                "via {{channel}} from account {{account}}.")
    if "total" in allowed and "entity.counterparty" in allowed:
        return ("You spent {{total}} with {{entity.counterparty}} in {{period}}, "
                "across {{record_count}} transactions.")
    if "balance_total" in allowed:
        return "Your available balance is {{balance_total}} across {{count}} accounts."
    if "shown_total" in allowed:
        return ("The top {{group_count}} account for {{shown_total}} in {{period}}; "
                "this is a partial view limited to the groups below.")
    if "total" in allowed and "count" in allowed and "period" in allowed:
        return "{{count}} transactions match in {{period}}, totalling {{total}}."
    if "total" in allowed and "period" in allowed:
        return "Total for {{period}} was {{total}} across {{record_count}} transactions."
    if "total" in allowed:
        return "The total is {{total}} across {{record_count}} records."
    if "count" in allowed:
        return "There are {{count}} matching transactions."
    return "The result covers {{record_count}} records."


PERIODS = (
    ("month before last", "month_before_last"), ("last month", "last_month"),
    ("this month", "this_month"), ("last quarter", "last_quarter"),
    ("this quarter", "this_quarter"), ("last year", "last_year"), ("this year", "this_year"),
    ("last 6 months", "last_6_months"), ("last six months", "last_6_months"),
    ("last 90 days", "last_90_days"), ("last 30 days", "last_30_days"),
    ("last 7 days", "last_7_days"), ("last week", "last_7_days"),
    ("yesterday", "yesterday"), ("today", "today"), ("all time", "all_time"),
)

KNOWN_NAMES = ("swiggy instamart", "swiggy", "zomato", "amazon pay india", "amazon", "uber",
               "ola", "airtel", "jio", "bigbasket", "flipkart", "reliance", "bajaj",
               "selection electronics", "selection mobile", "selection")


def _scope_and_plan(question: str) -> str:
    """Emit a scope verdict or plan from keyword matching.

    An unknown capitalised name after with/to/for/from is passed through as the counterparty
    so the resolver's NOT_FOUND path is exercised.
    """
    q = question.lower()
    if any(w in q for w in ("stock price", "weather", "bitcoin", "apple's stock",
                            "who is", "capital of", "credit score", "loan")):
        return json.dumps({"scope": "out_of_scope",
                           "reason": "I can analyse your bank transactions, balances and "
                                     "counterparties, but I don't have market or "
                                     "general-knowledge data."})
    if any(w in q for w in ("payroll", "headcount", "budget", "forecast", "profit",
                            "revenue", "reconcil", "vendor invoice", "category")):
        topic = next(w for w in ("payroll", "headcount", "budget", "forecast", "profit",
                                 "revenue", "reconcil", "vendor invoice", "category") if w in q)
        topic = {"reconcil": "reconciliation", "category": "spend categories"}.get(topic, topic)
        return json.dumps({"scope": "data_unavailable",
                           "reason": f"The records hold bank transactions, accounts and "
                                     f"banks, but nothing about {topic}, so I can't answer "
                                     f"that reliably."})

    period = None
    for phrase, rel in PERIODS:
        if phrase in q:
            period = {"relative": rel}
            break

    m = re.search(r"\butr\b[:\s#]*([A-Za-z0-9+/=]{8,})", question, re.I)
    if m:
        return _plan(intent="reference_lookup", reference=m.group(1), reference_kind="utr")
    m = re.search(r"\b(?:ref(?:erence)?(?:\s*(?:no|number|id))?)[:\s#]*([A-Za-z0-9]{6,})",
                  question, re.I)
    if m:
        return _plan(intent="reference_lookup", reference=m.group(1), reference_kind="reference")

    txn_type = None
    if re.search(r"\b(spent|spend|paid|pay|sent|debit|debits)\b", q):
        txn_type = "debit"
    elif re.search(r"\b(receive[ds]?|credited|credit|credits|got|incoming)\b", q):
        txn_type = "credit"

    min_amount = max_amount = None
    m = re.search(r"(?:less than|under|below|smaller than)\s*(?:rs\.?|₹|rupees)?\s*([\d,]+)", q)
    if m:
        max_amount = float(m.group(1).replace(",", ""))
    m = re.search(r"(?:more than|over|above|greater than|exceeding)\s*(?:rs\.?|₹|rupees)?\s*([\d,]+)", q)
    if m:
        min_amount = float(m.group(1).replace(",", ""))
    m = re.search(r"between\s*(?:rs\.?|₹)?\s*([\d,]+)\s*(?:and|to)\s*(?:rs\.?|₹)?\s*([\d,]+)", q)
    if m:
        min_amount, max_amount = float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))

    channel = None
    for ch in ("upi", "neft", "imps", "rtgs", "cheque"):
        if re.search(rf"\b{ch}\b", q):
            channel = ch.upper()
            break

    last4 = None
    m = re.search(r"(?:ending|ends? in|account)\s*(?:in\s*)?(\d{4})\b", q)
    if m:
        last4 = m.group(1)

    cp = None
    for name in KNOWN_NAMES:
        if name in q:
            cp = name
            break
    if cp is None:
        m = re.search(r"\b(?:with|to|from|pay|paid)\s+([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*)*)", question)
        if m and m.group(1).lower() not in ("upi", "neft", "imps"):
            cp = m.group(1)

    wants_count = bool(re.search(r"\bhow many\b|\bnumber of\b|\bcount of\b", q))
    wants_list = bool(re.search(r"\b(list|show|which|what are|give me)\b", q)) and \
        bool(re.search(r"transactions?|payments?|debits?|credits?", q))

    common = dict(date_range=period, transaction_type=txn_type, channel=channel,
                  account_last4=last4, min_amount=min_amount, max_amount=max_amount)
    # A listing question asks WHICH accounts or banks exist; a money question that merely
    # mentions "my accounts" is still a money question.
    asks_amount = bool(re.search(r"\bhow much\b|\btotal\b|\bsum\b|\bspent?\b|\bspend\b|"
                                 r"\bcredited\b|\bdebited\b|\breceive[ds]?\b|\bpaid\b|"
                                 r"\bbalance\b|\bhow many\b", q))
    if not asks_amount and re.search(r"\bbanks?\b|\baccounts?\b", q):
        return _plan(intent="account_list", account_last4=last4)
    if "balance" in q:
        return _plan(intent="balance", account_last4=last4)
    if re.search(r"\b(largest|biggest|highest)\b", q):
        return _plan(intent="largest_transactions", limit=10, **common)
    if re.search(r"\b(who|whom)\b.*\b(most|top)\b|\btop\b.*\b(counterpart|payee|merchant)", q):
        return _plan(intent="top_counterparties", metric="count" if wants_count else "sum",
                     limit=10, **common)
    if "by channel" in q or "per channel" in q or re.search(r"\bsplit\b.*\b(upi|channel)", q):
        return _plan(intent="channel_breakdown", metric="sum", **common)
    if "by account" in q or "per account" in q:
        return _plan(intent="account_summary", metric="sum", group_by="account", **common)
    if "by month" in q or "trend" in q or "over time" in q or "monthly" in q:
        return _plan(intent="trend", metric="sum", group_by="month", **common)
    if wants_list and not wants_count:
        return _plan(intent="transaction_lookup", counterparty_name=cp, limit=100, **common)
    if cp:
        return _plan(intent="counterparty_spend", counterparty_name=cp,
                     metric="count" if wants_count else "sum", **common)
    return _plan(intent="spend_summary", metric="count" if wants_count else "sum", **common)


def _delta(system: str, question: str) -> str:
    q = question.lower()
    delta: dict = {}
    clear: list[str] = []

    if "month before" in q or "previous month" in q:
        prev = json.loads(system.split("Previous plan:")[1].split("The previous plan's period")[0].strip())
        cur = (prev.get("date_range") or {}).get("relative")
        delta["date_range"] = {"relative": "month_before_last" if cur == "last_month"
                               else "last_month"}
    elif "by channel" in q:
        delta["group_by"] = "channel"
    elif "by account" in q:
        delta["group_by"] = "account"
    elif "everyone" in q or "all counterparties" in q:
        clear.append("counterparty_name")
        delta["intent"] = "spend_summary"
    elif "just the credits" in q or "only credits" in q:
        delta["transaction_type"] = "credit"
    elif "show me those" in q or "list them" in q:
        delta["intent"] = "transaction_lookup"
    else:
        m = re.search(r"(?:under|below|less than)\s*([\d,]+)", q)
        if m:
            delta["max_amount"] = float(m.group(1).replace(",", ""))
        for name in KNOWN_NAMES:
            if name in q:
                delta["counterparty_name"] = name
                delta["intent"] = "counterparty_spend"
                break

    return json.dumps({"scope": "in_scope", "delta": delta, "clear": clear})
