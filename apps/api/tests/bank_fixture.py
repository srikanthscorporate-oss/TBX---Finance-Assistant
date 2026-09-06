"""CSV-derived fixtures shared by the bank-schema tests.

Everything here is computed from data/raw/*.csv with plain Python so expected values
are independent of the compiler and pipeline. Only the deterministic narration parser
and the crypto helpers are imported from the app, because the CSV is plaintext and
the stored counterparty/channel columns are defined by parse_narration.
"""
from __future__ import annotations

import csv
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.agents.context import DatasetContext
from app.db.clickhouse import ClickHouseClient
from app.services.dates import DatasetCalendar
from app.services.narration import parse_narration
from app.services.resolver import AccountRecord, CounterpartyRecord

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "raw"


@dataclass(frozen=True)
class Txn:
    transaction_id: str
    account_id: str
    entity_id: str
    bank_code: str
    txn_date: date
    transaction_type: str
    description: str
    counterparty: str
    channel: str
    amount: float
    reference: str
    utr: str


def read_csv(name: str) -> list[dict]:
    with (RAW / name).open(newline="") as fh:
        return list(csv.DictReader(fh))


def load_accounts() -> dict[str, dict]:
    return {r["account_id"]: r for r in read_csv("account.csv")}


def load_banks() -> dict[str, str]:
    return {r["bank_code"]: r["bank_name"] for r in read_csv("bank.csv")}


def load_transactions(accounts: dict[str, dict]) -> list[Txn]:
    out: list[Txn] = []
    for r in read_csv("transaction.csv"):
        acct = accounts[r["account_id"]]
        cp, ch = parse_narration(r["description"])
        out.append(Txn(
            transaction_id=r["transaction_id"], account_id=r["account_id"],
            entity_id=acct["entity_id"], bank_code=acct["bank_code"],
            txn_date=date.fromisoformat(r["transaction_date"][:10]),
            transaction_type=r["transaction_type"], description=r["description"],
            counterparty=cp, channel=ch, amount=float(r["transaction_amount"]),
            reference=r["transaction_reference_id"], utr=r["utr_number"]))
    return out


def default_entity(txns: list[Txn]) -> str:
    """The busiest entity, matching the API's default scoping."""
    return Counter(t.entity_id for t in txns).most_common(1)[0][0]


def calendar(txns: list[Txn]) -> DatasetCalendar:
    return DatasetCalendar(min_date=min(t.txn_date for t in txns),
                           max_date=max(t.txn_date for t in txns))


def build_context(accounts: dict[str, dict], banks: dict[str, str], txns: list[Txn],
                  dataset_version: str = "csvtest") -> DatasetContext:
    """A DatasetContext equivalent to what state.build_dataset_context reads from the DB."""
    counts: Counter[str] = Counter()
    channels: dict[str, Counter[str]] = defaultdict(Counter)
    entities: dict[str, set[str]] = defaultdict(set)
    for t in txns:
        if not t.counterparty:
            continue
        counts[t.counterparty] += 1
        channels[t.counterparty][t.channel] += 1
        entities[t.counterparty].add(t.entity_id)
    counterparties = [
        CounterpartyRecord(name, n, channels[name].most_common(1)[0][0], frozenset(entities[name]))
        for name, n in counts.most_common()
    ]
    acct_records = [
        AccountRecord(r["account_id"], r["entity_id"], r["account_number"][-4:], r["bank_code"],
                      banks.get(r["bank_code"], r["bank_code"]), int(r["program_id"]),
                      float(r["available_balance"]))
        for r in accounts.values()
    ]
    entity_order = [e for e, _ in Counter(t.entity_id for t in txns).most_common()]
    return DatasetContext(
        calendar=calendar(txns), counterparties=counterparties, accounts=acct_records,
        banks=banks, entities=entity_order, currency="INR",
        dataset_version=dataset_version, default_entity=entity_order[0])


def ch_client(**kw) -> ClickHouseClient:
    return ClickHouseClient(
        host=os.getenv("CH_HOST", "127.0.0.1"), port=int(os.getenv("CH_PORT", "18123")),
        user=os.getenv("CH_ADMIN_USER", "tbx_admin"),
        password=os.getenv("CH_ADMIN_PASSWORD", "change-me-admin"), **kw)


def data_key() -> str:
    """TBX_DATA_KEY from the environment, else from the repo's .env."""
    key = os.getenv("TBX_DATA_KEY", "").strip()
    if key:
        return key
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            m = re.match(r"^\s*TBX_DATA_KEY\s*=\s*(.+?)\s*$", line)
            if m:
                return m.group(1).strip("'\"")
    raise RuntimeError("TBX_DATA_KEY is not set and .env has no value")
