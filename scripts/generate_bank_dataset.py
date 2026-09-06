#!/usr/bin/env python3
"""Generate bank.csv, account.csv and transaction.csv in the shape of docs/TBX - Database Schema.md.

Descriptions, reference formats and bank codes follow the sample rows in that document so
the data behaves like the real export. Rows stream straight to disk, so --rows 20000000 is
fine on a laptop; expect about 20 seconds per million rows.

    python3 scripts/generate_bank_dataset.py --out data/raw --rows 200000
    python3 scripts/generate_bank_dataset.py --out data/scale --rows 20000000
"""
from __future__ import annotations

import argparse
import csv
import itertools
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path

BANKS = [
    ("HDFC", "HDFC BANK LIMITED"), ("ICIC", "ICICI BANK LIMITED"),
    ("SBIN", "STATE BANK OF INDIA"), ("UTIB", "AXIS BANK LIMITED"),
    ("KKBK", "KOTAK MAHINDRA BANK LIMITED"), ("CNRB", "CANARA BANK"),
    ("UBIN", "UNION BANK OF INDIA"), ("AUBL", "AU SMALL FINANCE BANK LIMITED"),
    ("TMBL", "TAMILNAD MERCANTILE BANK LIMITED"), ("RATN", "RBL BANK LIMITED"),
]
PROGRAMS = [21, 4, 46]

COUNTERPARTIES = [
    "SELECTION ELECTRONICS", "NAVYUG SELECTION", "SELECTRICITY TWO PRIVATE LIMITED",
    "UMANG SELECTION", "SELECTION MOBILE", "SELECTIONMALIGAI", "RELIANCEDIGITAL RETAIL LTD",
    "PARESH VIKRANT GHASE", "Gautam singh", "BAJAJ FINANCE LIMITED", "TATA CAPITAL",
    "AMAZON SELLER SERVICES", "FLIPKART INTERNET PVT LTD", "VIVO MOBILE INDIA",
    "SAMSUNG INDIA ELECTRONICS", "LG ELECTRONICS INDIA", "HAVELLS INDIA LIMITED",
    "GST PAYMENT", "SALARY DISBURSEMENT", "SWIGGY", "SWIGGY INSTAMART", "ZOMATO",
    "AMAZON PAY INDIA", "UBER INDIA", "OLA CABS", "AIRTEL", "JIO PLATFORMS", "BIGBASKET",
]
PLACES = ["DAHISAR EAST", "HAPUR", "SAKET DELHI", "PUNE", "MADURAI", "SURAT", "INDORE"]


def money(lo: float, hi: float, rnd: random.Random) -> str:
    return f"{rnd.uniform(lo, hi):.2f}"


def describe(kind: str, rnd: random.Random, acct_no: str) -> tuple[str, str, str]:
    """Return (description, reference_id, utr) in the mix of formats seen in the export."""
    cp = rnd.choice(COUNTERPARTIES)
    n = rnd.randint(10_000_000, 99_999_999)
    style = rnd.random()
    if style < 0.30:
        ref = f"HDFCH{rnd.randint(10**9, 10**10 - 1)}"
        bank = rnd.choice(BANKS)[0]
        desc = f"NEFT  - {bank}000{rnd.randint(1000, 9999)} - {n} - {rnd.randint(10**11, 10**14)} - {cp}"
        utr = uuid.UUID(int=rnd.getrandbits(128)).hex + "=="
    elif style < 0.50:
        ref = str(rnd.randint(10**11, 10**12 - 1))
        desc = f"UPI-{cp}-XXXXXX{rnd.randint(1000, 9999)}-{rnd.choice(BANKS)[0]}0002125-{ref}-{n}"
        utr = uuid.UUID(int=rnd.getrandbits(128)).hex
    elif style < 0.65:
        ref = f"S{rnd.randint(10**7, 10**8 - 1)}"
        desc = f"IMPS/P2A/{rnd.randint(10**11, 10**12 - 1)}/{rnd.choice(BANKS)[0]}/{acct_no}/00/INET/{cp}/INWD48"
        utr = ""
    elif style < 0.80:
        ref = str(rnd.randint(10**9, 10**10 - 1))
        desc = f"FT -  {n} -  {acct_no} - {cp}   {rnd.choice(PLACES)}"
        utr = uuid.UUID(int=rnd.getrandbits(128)).hex
    elif style < 0.90:
        ref = f"S{rnd.randint(10**7, 10**8 - 1)}"
        desc = f"R/RATNR5{n}00100235/ZBFLCTP405PBL{rnd.randint(10**7, 10**8 - 1)}//{cp}/{cp}"
        utr = ""
    else:
        ref = "" if rnd.random() < 0.5 else f"S{rnd.randint(10**6, 10**7 - 1)}"
        desc = rnd.choice(["IMPS charges", "Cheque Deposits", "SMS ALERT CHARGES",
                           "INTEREST CREDIT", f"IMPS OW/{n}/{cp}/SBIN/{rnd.randint(10**10, 10**11)}"])
        utr = ""
    if kind == "credit" and style >= 0.9:
        desc = "Cheque Deposits" if rnd.random() < 0.5 else "INTEREST CREDIT"
    return desc, ref, utr


def generate(out: Path, rows: int, entities: int, accounts: int, seed: int,
             start: datetime, end: datetime) -> None:
    rnd = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)

    with (out / "bank.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["bank_code", "bank_name"])
        w.writerows(BANKS)

    entity_ids = [str(uuid.UUID(int=rnd.getrandbits(128))) for _ in range(entities)]
    account_rows = []
    for i in range(accounts):
        code, _ = rnd.choice(BANKS)
        account_rows.append([
            str(uuid.UUID(int=rnd.getrandbits(128))),
            entity_ids[i % entities],
            str(rnd.randint(10**13, 10**14 - 1)),
            rnd.choice(PROGRAMS),
            money(-150_000_000, 250_000_000, rnd),
            code,
        ])
    with (out / "account.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["account_id", "entity_id", "account_number", "program_id",
                    "available_balance", "bank_code"])
        w.writerows(account_rows)

    cum = list(itertools.accumulate(rnd.paretovariate(1.2) for _ in account_rows))
    span = int((end - start).total_seconds())
    with (out / "transaction.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["transaction_id", "account_id", "transaction_date", "transaction_type",
                    "description", "transaction_amount", "transaction_reference_id",
                    "utr_number"])
        batch = []
        for i in range(rows):
            acct = rnd.choices(account_rows, cum_weights=cum)[0]
            kind = "debit" if rnd.random() < 0.62 else "credit"
            ts = start + timedelta(seconds=rnd.randrange(span))
            desc, ref, utr = describe(kind, rnd, acct[2])
            amt = money(100, 5_000, rnd) if rnd.random() < 0.7 else money(5_000, 2_500_000, rnd)
            batch.append([
                str(uuid.UUID(int=rnd.getrandbits(128))), acct[0],
                ts.strftime("%Y-%m-%d %H:%M:%S.%f"), kind, desc, amt, ref, utr,
            ])
            if len(batch) >= 50_000:
                w.writerows(batch)
                batch.clear()
                if (i + 1) % 1_000_000 == 0:
                    print(f"  {i + 1:,} transactions", flush=True)
        w.writerows(batch)
    print(f"wrote {len(BANKS)} banks, {accounts} accounts, {rows:,} transactions to {out}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/raw")
    ap.add_argument("--rows", type=int, default=200_000)
    ap.add_argument("--entities", type=int, default=40)
    ap.add_argument("--accounts", type=int, default=120)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end", default="2026-08-31")
    a = ap.parse_args()
    generate(Path(a.out), a.rows, a.entities, a.accounts, a.seed,
             datetime.fromisoformat(a.start), datetime.fromisoformat(a.end))


if __name__ == "__main__":
    main()
