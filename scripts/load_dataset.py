#!/usr/bin/env python3
"""Load CSVs from data/raw into ClickHouse, with validation and a quality report.

Deliberately schema-driven: the column map below is the contract. When the real
TBX dataset lands tomorrow, adjust COLUMN_MAP (and only COLUMN_MAP) to match
their headers -- nothing downstream needs to change.

Refuses to load a file whose required columns are missing, rather than loading
partial data that would silently produce wrong answers.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

DB = "tbx_finance"

# table -> (csv filename, required columns)
TABLES: dict[str, tuple[str, list[str]]] = {
    "vendors": ("vendors.csv",
                ["vendor_id", "vendor_name", "legal_name", "category", "status",
                 "country", "currency", "onboarded_at"]),
    "accounts": ("accounts.csv",
                 ["account_code", "account_name", "account_type", "parent_code", "is_active"]),
    "transactions": ("transactions.csv",
                     ["transaction_id", "txn_date", "posted_at", "vendor_id", "account_code",
                      "category", "description", "amount", "currency", "direction", "status",
                      "payment_method", "reconciliation_status", "invoice_ref", "payout_id"]),
    "vendor_payouts": ("vendor_payouts.csv",
                       ["payout_id", "payout_date", "vendor_id", "amount", "currency",
                        "status", "method", "invoice_count", "reference"]),
    "reconciliation": ("reconciliation.csv",
                       ["recon_id", "transaction_id", "status", "matched_at",
                        "bank_reference", "variance_amount", "note"]),
}

LOAD_ORDER = ["vendors", "accounts", "transactions", "vendor_payouts", "reconciliation"]


class ClickHouse:
    def __init__(self, url: str, user: str, password: str):
        self.url, self.user, self.password = url.rstrip("/"), user, password

    def execute(self, sql: str, body: bytes | None = None) -> str:
        params = urllib.parse.urlencode({"query": sql})
        req = urllib.request.Request(f"{self.url}/?{params}", data=body or b"", method="POST")
        req.add_header("X-ClickHouse-User", self.user)
        req.add_header("X-ClickHouse-Key", self.password)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read().decode()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"ClickHouse error: {e.read().decode()[:600]}") from None


def validate(path: Path, required: list[str]) -> tuple[list[dict], dict]:
    """Read a CSV and report on its quality. Missing required columns is fatal."""
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        headers = reader.fieldnames or []
        missing = [c for c in required if c not in headers]
        if missing:
            raise SystemExit(
                f"FATAL {path.name}: missing required column(s): {', '.join(missing)}\n"
                f"  found: {', '.join(headers)}\n"
                f"  Update COLUMN_MAP in scripts/load_dataset.py to map the real headers."
            )
        rows = list(reader)

    extra = [c for c in headers if c not in required]
    nulls = {c: sum(1 for r in rows if not (r.get(c) or "").strip()) for c in required}
    id_col = required[0]
    ids = [r[id_col] for r in rows]
    report = {
        "file": path.name,
        "rows": len(rows),
        "columns": len(headers),
        "unexpected_columns": extra,
        "duplicate_ids": len(ids) - len(set(ids)),
        "null_counts": {k: v for k, v in nulls.items() if v},
        "valid_pct": 100.0,
    }
    bad = report["duplicate_ids"] + sum(report["null_counts"].values())
    if rows:
        report["valid_pct"] = round(100.0 * (1 - bad / (len(rows) * len(required))), 3)
    return rows, report


def referential_checks(data: dict[str, list[dict]]) -> list[str]:
    problems = []
    vendor_ids = {r["vendor_id"] for r in data.get("vendors", [])}
    account_codes = {r["account_code"] for r in data.get("accounts", [])}
    txn_ids = {r["transaction_id"] for r in data.get("transactions", [])}

    for table, col, universe, label in [
        ("transactions", "vendor_id", vendor_ids, "vendors"),
        ("transactions", "account_code", account_codes, "accounts"),
        ("vendor_payouts", "vendor_id", vendor_ids, "vendors"),
        ("reconciliation", "transaction_id", txn_ids, "transactions"),
    ]:
        if table not in data or not universe:
            continue
        orphans = {r[col] for r in data[table] if r.get(col) and r[col] not in universe}
        if orphans:
            problems.append(
                f"{table}.{col}: {len(orphans)} value(s) not present in {label} "
                f"(e.g. {sorted(orphans)[:3]})"
            )
    return problems


# Columns declared Nullable in the schema. An empty CSV cell must become the
# TabSeparated NULL marker (\\N); an empty string will not parse as a DateTime.
NULLABLE_COLUMNS: dict[str, set[str]] = {
    "reconciliation": {"matched_at"},
}


def to_tsv(rows: list[dict], columns: list[str], table: str = "") -> bytes:
    nullable = NULLABLE_COLUMNS.get(table, set())
    out = []
    for r in rows:
        fields = []
        for c in columns:
            v = (r.get(c) or "").strip()
            if not v and c in nullable:
                fields.append("\\N")
                continue
            fields.append(v.replace("\\", "\\\\").replace("\t", " ").replace("\n", " "))
        out.append("\t".join(fields))
    return ("\n".join(out) + "\n").encode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--url", default="http://localhost:18123")
    ap.add_argument("--user", default="tbx_admin")
    ap.add_argument("--password", default="change-me-admin")
    ap.add_argument("--version", default=None)
    ap.add_argument("--truncate", action="store_true", default=True)
    ap.add_argument("--report", default="data/processed/data_quality.json")
    args = ap.parse_args()

    raw = Path(args.raw)
    ch = ClickHouse(args.url, args.user, args.password)
    ch.execute(f"CREATE DATABASE IF NOT EXISTS {DB}")
    schema = Path("infra/clickhouse/001_schema.sql").read_text()
    for stmt in [s.strip() for s in schema.split(";") if s.strip()]:
        ch.execute(stmt)

    data: dict[str, list[dict]] = {}
    reports = []
    hasher = hashlib.sha256()

    for table in LOAD_ORDER:
        fname, required = TABLES[table]
        path = raw / fname
        if not path.exists():
            print(f"  skip {fname} (not present)")
            continue
        rows, report = validate(path, required)
        data[table] = rows
        reports.append(report)
        hasher.update(path.read_bytes())

        if args.truncate:
            ch.execute(f"TRUNCATE TABLE IF EXISTS {DB}.{table}")
        if rows:
            cols = ",".join(required)
            ch.execute(f"INSERT INTO {DB}.{table} ({cols}) FORMAT TabSeparated",
                       to_tsv(rows, required, table))
        print(f"  loaded {table:16} {len(rows):>7,} rows   valid {report['valid_pct']}%")

    problems = referential_checks(data)
    version = args.version or f"{datetime.utcnow():%Y%m%d-%H%M%S}"
    checksum = hasher.hexdigest()[:16]

    ch.execute(
        f"INSERT INTO {DB}.dataset_versions "
        "(dataset_version, loaded_at, source_files, row_counts, checksum) FORMAT TabSeparated",
        to_tsv([{
            "dataset_version": version,
            "loaded_at": f"{datetime.utcnow():%Y-%m-%d %H:%M:%S}",
            "source_files": ",".join(sorted(f for f, _ in TABLES.values())),
            "row_counts": json.dumps({k: len(v) for k, v in data.items()}),
            "checksum": checksum,
        }], ["dataset_version", "loaded_at", "source_files", "row_counts", "checksum"]),
    )

    out = {
        "dataset_version": version, "checksum": checksum,
        "tables": reports, "referential_problems": problems,
        "generated_at": datetime.utcnow().isoformat(),
    }
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(out, indent=2))

    print(f"\n  dataset_version={version}  checksum={checksum}")
    if problems:
        print("\n  REFERENTIAL INTEGRITY PROBLEMS:")
        for p in problems:
            print(f"    - {p}")
        return 1
    print("  referential integrity: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
