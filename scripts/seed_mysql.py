#!/usr/bin/env python3
"""Seed the compose MySQL with the bundled CSVs so the Data Source page can be
tried against a real endpoint locally.

    apps/api/.venv/bin/python scripts/seed_mysql.py            # 127.0.0.1:13306
    apps/api/.venv/bin/python scripts/seed_mysql.py --limit 200000

Loads bank.csv, account.csv and transaction.csv from data/raw into the schema in
infra/mysql/001_schema.sql, plaintext -- this is a *source* system, encryption
happens on ingest into ClickHouse (apps/api/app/services/ingest.py).
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
import pymysql  # noqa: E402

TABLES = {
    "bank": ("bank.csv", ["bank_code", "bank_name"]),
    "account": ("account.csv", ["account_id", "entity_id", "account_number", "program_id",
                                "available_balance", "bank_code"]),
    "transaction": ("transaction.csv", ["transaction_id", "account_id", "transaction_date",
                                        "transaction_type", "description", "transaction_amount",
                                        "transaction_reference_id", "utr_number"]),
}
CHUNK = 5_000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=13306)
    ap.add_argument("--database", default="tbx_app")
    ap.add_argument("--user", default="tbx")
    ap.add_argument("--password", default="change-me-mysql")
    ap.add_argument("--limit", type=int, default=0, help="cap transaction rows (0 = all)")
    args = ap.parse_args()

    conn = pymysql.connect(host=args.host, port=args.port, user=args.user,
                           password=args.password, database=args.database,
                           autocommit=False, charset="utf8mb4", local_infile=False)
    schema = "\n".join(line for line in Path("infra/mysql/001_schema.sql").read_text().splitlines()
                       if not line.lstrip().startswith("--"))
    with conn.cursor() as cur:
        for stmt in [s.strip() for s in schema.split(";") if s.strip()]:
            cur.execute(stmt)
    conn.commit()

    for table, (fname, cols) in TABLES.items():
        path = Path(args.raw) / fname
        if not path.exists():
            print(f"  skip {fname} (not present)")
            continue
        placeholders = ", ".join(["%s"] * len(cols))
        sql = f"INSERT INTO `{table}` ({', '.join(cols)}) VALUES ({placeholders})"
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM `{table}`")
            n = 0
            batch = []
            with path.open(newline="") as fh:
                for r in csv.DictReader(fh):
                    batch.append([(r.get(c) or None) if c not in ("bank_code", "account_id",
                                                                  "entity_id", "transaction_id")
                                  else r.get(c, "") for c in cols])
                    n += 1
                    if len(batch) >= CHUNK:
                        cur.executemany(sql, batch)
                        batch.clear()
                        conn.commit()
                    if args.limit and table == "transaction" and n >= args.limit:
                        break
                if batch:
                    cur.executemany(sql, batch)
        conn.commit()
        print(f"  seeded {table:12} {n:>10,} rows")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
