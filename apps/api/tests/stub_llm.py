"""A deterministic stand-in for a real LLM.

Lets the full pipeline -- validation, resolution, compilation, execution,
verification, confidence, composition -- be exercised in CI and before any API
key exists. It is NOT a fallback for production: it recognises a fixed set of
phrasings and is only ever wired in by tests and the offline demo.
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
    # Read the advertised vocabulary only, not every brace pair in the prompt.
    line = ""
    for ln in system.splitlines():
        if ln.strip().startswith("{{") and "}}," in ln or (
                ln.strip().startswith("{{") and ln.strip().endswith("}}")):
            line = ln
            break
    allowed = set(re.findall(r"\{\{([a-z][a-z0-9_.]*)\}\}", line))
    if "rate" in allowed:
        return "{{rate}} of transactions are reconciled for {{period}}, across {{record_count}} records."
    if "total" in allowed and "entity.vendor_name" in allowed:
        return "You spent {{total}} with {{entity.vendor_name}} in {{period}}, across {{record_count}} transactions."
    if "shown_total" in allowed:
        return ("The top {{group_count}} account for {{shown_total}} in {{period}}; "
                "this is a partial view limited to the groups below.")
    if "total" in allowed and "period" in allowed:
        return "Total spend for {{period}} was {{total}} across {{record_count}} transactions."
    if "total" in allowed:
        return "The total is {{total}} across {{record_count}} records."
    if "count" in allowed:
        return "There are {{count}} matching transactions."
    return "The result covers {{record_count}} records."


def _scope_and_plan(question: str) -> str:
    q = question.lower()

    if any(w in q for w in ("stock price", "weather", "bitcoin", "apple's stock",
                            "who is", "capital of")):
        return json.dumps({"scope": "out_of_scope",
                           "reason": "I can analyse spend, vendor payouts and "
                                     "reconciliation from this dataset, but I don't have "
                                     "market or general-knowledge data."})

    if any(w in q for w in ("gst", "tax", "payroll", "headcount", "budget",
                            "forecast", "profit", "revenue", "salary")):
        topic = next(w for w in ("gst", "tax", "payroll", "headcount", "budget",
                                 "forecast", "profit", "revenue", "salary") if w in q)
        return json.dumps({"scope": "data_unavailable",
                           "reason": f"This dataset has transactions, payouts and "
                                     f"reconciliation records, but no {topic} data, so I "
                                     f"can't answer that reliably."})

    period = None
    for phrase, rel in (("month before last", "month_before_last"),
                        ("last month", "last_month"), ("this month", "this_month"),
                        ("last quarter", "last_quarter"), ("last year", "last_year"),
                        ("last 6 months", "last_6_months"),
                        ("last six months", "last_6_months"),
                        ("last 30 days", "last_30_days")):
        if phrase in q:
            period = {"relative": rel}
            break

    vendor = None
    for name in ("acme technologies", "acme logistics", "acme", "northwind",
                 "brightpath", "globex", "initech", "umbrella", "vertex",
                 "skyline", "corevault", "pinnacle", "stationery"):
        if name in q:
            vendor = name
            break
    if vendor is None:
        # A real planner copies whatever name the user wrote; the resolver -- not
        # the planner -- decides whether it exists. Mimic that here so the
        # NOT_FOUND path is actually exercised.
        m = re.search(r"\b(?:with|to|for|from)\s+([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*)*)",
                      question)
        if m and m.group(1).lower() not in ("marketing", "travel", "legal"):
            vendor = m.group(1)

    # A category word inside a matched vendor name ("Vertex Legal") is part of
    # the vendor, not a category filter. Vendor detection therefore wins.
    category = None
    if vendor is None:
        for cat in ("marketing", "travel", "legal", "logistics", "utilities",
                    "recruitment"):
            if cat in q:
                category = cat.title()
                break

    wants_count = bool(re.search(r"\bhow many\b|\bnumber of\b|\bcount of\b", q))
    wants_rate = bool(re.search(r"\bproportion\b|\bpercentage\b|\bwhat share\b|%", q))

    if wants_rate and re.search(r"matched|reconcil", q):
        return _plan(intent="reconciliation_rate", date_range=period)
    if "unreconciled" in q or ("not" in q and "reconciled" in q):
        return _plan(intent="unreconciled", metric="count", limit=1000,
                     date_range=period)
    if "reconciliation rate" in q or ("what" in q and "reconciled" in q and "%" in q):
        return _plan(intent="reconciliation_rate", date_range=period)
    if "top" in q and "vendor" in q:
        return _plan(intent="top_vendors", metric="sum", group_by="vendor",
                     date_range=period, limit=10)
    if "by category" in q or "per category" in q:
        return _plan(intent="total_spend", metric="sum", group_by="category",
                     date_range=period)
    if "by month" in q or "trend" in q or "over time" in q:
        return _plan(intent="trend", metric="sum", group_by="month", date_range=period)
    if "payout" in q:
        return _plan(intent="vendor_payouts" if vendor else "payout_status",
                     vendor_name=vendor, metric="sum", date_range=period)
    if category:
        return _plan(intent="category_spend", category=category,
                     metric="count" if wants_count else "sum", date_range=period)
    if vendor:
        return _plan(intent="vendor_spend", vendor_name=vendor,
                     metric="count" if wants_count else "sum", date_range=period)
    return _plan(intent="total_spend", metric="count" if wants_count else "sum",
                 date_range=period)


def _delta(system: str, question: str) -> str:
    q = question.lower()
    delta: dict = {}
    clear: list[str] = []

    if "month before" in q or "previous month" in q:
        prev = json.loads(system.split("Previous plan:")[1].split("Previous period")[0].strip())
        cur = (prev.get("date_range") or {}).get("relative")
        delta["date_range"] = {"relative": "month_before_last" if cur == "last_month"
                               else "last_month"}
    elif "by category" in q:
        delta["group_by"] = "category"
    elif "by vendor" in q:
        delta["group_by"] = "vendor"
    elif "all vendors" in q or "everyone" in q:
        clear.append("vendor_name")
        delta["intent"] = "total_spend"
    else:
        for name in ("globex", "northwind", "brightpath", "initech", "skyline"):
            if name in q:
                delta["vendor_name"] = name
                delta["intent"] = "vendor_spend"
                break

    return json.dumps({"scope": "in_scope", "delta": delta, "clear": clear})
