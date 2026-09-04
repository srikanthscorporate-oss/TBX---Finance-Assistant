#!/usr/bin/env python3
"""Generate a stand-in dataset shaped like the promised TBX starter data.

This exists so the pipeline can be built and evaluated before the real dataset
lands. It is NOT training data and never ships to production: the loader reads
whatever CSVs are in data/raw/, so swapping in the real files is a file copy.

Deliberately includes the messy cases the assistant must handle correctly:
  * two vendors sharing a first token ("Acme Technologies" / "Acme Logistics")
    so vendor ambiguity -> CLARIFICATION_REQUIRED can be exercised
  * a small number of unreconciled / disputed rows
  * one genuine payout outlier for the anomaly-callout bonus
  * no GST/tax column at all, so "how much GST did we pay?" must return
    DATA_UNAVAILABLE rather than a guess
"""
from __future__ import annotations

import argparse
import csv
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 20260904

CATEGORIES = [
    "Cloud Infrastructure", "Professional Services", "Marketing", "Travel",
    "Office Supplies", "Software Licenses", "Logistics", "Utilities",
    "Legal", "Recruitment",
]

VENDORS = [
    # (id, name, legal name, category, country)
    ("V1001", "Acme Technologies", "Acme Technologies Pvt Ltd", "Cloud Infrastructure", "IN"),
    ("V1002", "Acme Logistics", "Acme Logistics Pvt Ltd", "Logistics", "IN"),
    ("V1003", "Northwind Consulting", "Northwind Consulting LLP", "Professional Services", "IN"),
    ("V1004", "Brightpath Media", "Brightpath Media Pvt Ltd", "Marketing", "IN"),
    ("V1005", "Globex Software", "Globex Software Inc", "Software Licenses", "US"),
    ("V1006", "Initech Systems", "Initech Systems Pvt Ltd", "Software Licenses", "IN"),
    ("V1007", "Umbrella Facilities", "Umbrella Facilities Pvt Ltd", "Utilities", "IN"),
    ("V1008", "Vertex Legal", "Vertex Legal Associates", "Legal", "IN"),
    ("V1009", "Skyline Travel", "Skyline Travel Pvt Ltd", "Travel", "IN"),
    ("V1010", "Corevault Cloud", "Corevault Cloud Pvt Ltd", "Cloud Infrastructure", "IN"),
    ("V1011", "Pinnacle Recruitment", "Pinnacle Recruitment LLP", "Recruitment", "IN"),
    ("V1012", "Stationery Hub", "Stationery Hub Pvt Ltd", "Office Supplies", "IN"),
]

ACCOUNTS = [
    ("5010", "Cloud & Hosting", "expense", "5000"),
    ("5020", "Professional Fees", "expense", "5000"),
    ("5030", "Marketing & Advertising", "expense", "5000"),
    ("5040", "Travel & Entertainment", "expense", "5000"),
    ("5050", "Office & Admin", "expense", "5000"),
    ("5060", "Software & Subscriptions", "expense", "5000"),
    ("5070", "Freight & Logistics", "expense", "5000"),
    ("5080", "Utilities", "expense", "5000"),
    ("5090", "Legal & Compliance", "expense", "5000"),
    ("5100", "Recruitment", "expense", "5000"),
    ("5000", "Operating Expenses", "expense", ""),
]

CATEGORY_ACCOUNT = {
    "Cloud Infrastructure": "5010", "Professional Services": "5020",
    "Marketing": "5030", "Travel": "5040", "Office Supplies": "5050",
    "Software Licenses": "5060", "Logistics": "5070", "Utilities": "5080",
    "Legal": "5090", "Recruitment": "5100",
}

# Rough monthly spend scale per vendor, so totals look plausible rather than uniform.
VENDOR_SCALE = {
    "V1001": 1_800_000, "V1002": 420_000, "V1003": 950_000, "V1004": 700_000,
    "V1005": 1_100_000, "V1006": 380_000, "V1007": 260_000, "V1008": 340_000,
    "V1009": 300_000, "V1010": 880_000, "V1011": 450_000, "V1012": 90_000,
}

PAYMENT_METHODS = ["bank_transfer", "ach", "wire", "card", "upi"]


def month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def generate(outdir: Path, start: date, end: date) -> dict[str, int]:
    rng = random.Random(SEED)
    outdir.mkdir(parents=True, exist_ok=True)

    transactions, payouts, recons = [], [], []
    txn_n = payout_n = recon_n = 0

    for year, month in month_iter(start, end):
        month_start = date(year, month, 1)
        for vid, vname, _legal, category, _country in VENDORS:
            scale = VENDOR_SCALE[vid]
            n_txn = rng.randint(6, 22)
            # Seasonal wobble so month-over-month comparisons are meaningful.
            wobble = rng.uniform(0.75, 1.3)

            # One deliberate anomaly: Acme Technologies spikes in July 2026.
            if vid == "V1001" and (year, month) == (2026, 7):
                wobble = 4.2
                n_txn += 6

            payout_total = 0.0
            payout_n += 1
            payout_id = f"P{payout_n:06d}"

            for _ in range(n_txn):
                txn_n += 1
                day = rng.randint(1, 28)
                txn_date = month_start.replace(day=day)
                amount = round(max(500.0, rng.gauss(scale * wobble / n_txn, scale * 0.12 / n_txn)), 2)
                payout_total += amount

                status = rng.choices(
                    ["posted", "pending", "failed", "reversed"],
                    weights=[92, 5, 2, 1],
                )[0]
                recon_status = rng.choices(
                    ["matched", "unmatched", "pending", "disputed"],
                    weights=[85, 7, 6, 2],
                )[0]

                tid = f"T{txn_n:07d}"
                transactions.append({
                    "transaction_id": tid,
                    "txn_date": txn_date.isoformat(),
                    "posted_at": f"{txn_date.isoformat()} {rng.randint(8,19):02d}:{rng.randint(0,59):02d}:00",
                    "vendor_id": vid,
                    "account_code": CATEGORY_ACCOUNT[category],
                    "category": category,
                    "description": f"{vname} - invoice {rng.randint(1000,9999)}",
                    "amount": f"{amount:.2f}",
                    "currency": "INR",
                    "direction": "debit",
                    "status": status,
                    "payment_method": rng.choice(PAYMENT_METHODS),
                    "reconciliation_status": recon_status,
                    "invoice_ref": f"INV-{year}{month:02d}-{rng.randint(10000,99999)}",
                    "payout_id": payout_id,
                })

                recon_n += 1
                matched_at = (
                    f"{(txn_date + timedelta(days=rng.randint(1, 9))).isoformat()} 10:00:00"
                    if recon_status == "matched" else ""
                )
                recons.append({
                    "recon_id": f"R{recon_n:07d}",
                    "transaction_id": tid,
                    "status": recon_status,
                    "matched_at": matched_at,
                    "bank_reference": f"BNK{rng.randint(10**9, 10**10 - 1)}" if recon_status == "matched" else "",
                    "variance_amount": f"{round(rng.uniform(-250, 250), 2):.2f}" if recon_status == "disputed" else "0.00",
                    "note": "amount mismatch under review" if recon_status == "disputed" else "",
                })

            payouts.append({
                "payout_id": payout_id,
                "payout_date": month_start.replace(day=min(28, 25)).isoformat(),
                "vendor_id": vid,
                "amount": f"{payout_total:.2f}",
                "currency": "INR",
                "status": rng.choices(["completed", "pending", "failed", "scheduled"],
                                      weights=[90, 6, 2, 2])[0],
                "method": rng.choice(PAYMENT_METHODS),
                "invoice_count": n_txn,
                "reference": f"PAY-{year}{month:02d}-{vid}",
            })

    _write(outdir / "vendors.csv",
           ["vendor_id", "vendor_name", "legal_name", "category", "status", "country", "currency", "onboarded_at"],
           [{"vendor_id": v[0], "vendor_name": v[1], "legal_name": v[2], "category": v[3],
             "status": "active", "country": v[4], "currency": "INR",
             "onboarded_at": (start - timedelta(days=random.Random(SEED + i).randint(200, 1200))).isoformat()}
            for i, v in enumerate(VENDORS)])

    _write(outdir / "accounts.csv",
           ["account_code", "account_name", "account_type", "parent_code", "is_active"],
           [{"account_code": a[0], "account_name": a[1], "account_type": a[2],
             "parent_code": a[3], "is_active": "1"} for a in ACCOUNTS])

    _write(outdir / "transactions.csv", list(transactions[0].keys()), transactions)
    _write(outdir / "vendor_payouts.csv", list(payouts[0].keys()), payouts)
    _write(outdir / "reconciliation.csv", list(recons[0].keys()), recons)

    _write_data_dictionary(outdir / "data_dictionary.csv")

    return {
        "vendors": len(VENDORS), "accounts": len(ACCOUNTS),
        "transactions": len(transactions), "vendor_payouts": len(payouts),
        "reconciliation": len(recons),
    }


def _write(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _write_data_dictionary(path: Path) -> None:
    rows = [
        ("transactions", "transaction_id", "String", "Unique transaction identifier"),
        ("transactions", "txn_date", "Date", "Date the transaction occurred"),
        ("transactions", "vendor_id", "String", "FK to vendors.vendor_id"),
        ("transactions", "account_code", "String", "FK to accounts.account_code"),
        ("transactions", "category", "String", "Spend category"),
        ("transactions", "amount", "Decimal(2)", "Transaction amount, positive"),
        ("transactions", "currency", "String", "ISO 4217 currency code"),
        ("transactions", "direction", "String", "debit or credit"),
        ("transactions", "status", "String", "posted/pending/failed/reversed"),
        ("transactions", "reconciliation_status", "String", "matched/unmatched/pending/disputed"),
        ("vendor_payouts", "payout_id", "String", "Unique payout identifier"),
        ("vendor_payouts", "payout_date", "Date", "Date the payout was issued"),
        ("vendor_payouts", "amount", "Decimal(2)", "Total payout amount"),
        ("vendor_payouts", "status", "String", "completed/pending/failed/scheduled"),
        ("reconciliation", "recon_id", "String", "Unique reconciliation record"),
        ("reconciliation", "transaction_id", "String", "FK to transactions.transaction_id"),
        ("reconciliation", "status", "String", "matched/unmatched/pending/disputed"),
        ("reconciliation", "variance_amount", "Decimal(2)", "Difference vs bank record"),
        ("vendors", "vendor_id", "String", "Unique vendor identifier"),
        ("vendors", "vendor_name", "String", "Display name"),
        ("accounts", "account_code", "String", "Chart of accounts code"),
    ]
    _write(path, ["table", "column", "type", "description"],
           [{"table": t, "column": c, "type": ty, "description": d} for t, c, ty, d in rows])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default="2026-08-31")
    args = ap.parse_args()
    counts = generate(Path(args.out), date.fromisoformat(args.start), date.fromisoformat(args.end))
    for k, v in counts.items():
        print(f"{k:20} {v:>8,}")
