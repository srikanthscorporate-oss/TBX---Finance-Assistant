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
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DB = "tbx_finance"  # overridden by --db; the scale test loads into a sibling database

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

    # Applied to every INSERT. Parallel parsing of a 100k-row chunk plus the
    # background merges of the tables already loaded exceeded the ClickHouse
    # container's memory at 20M rows. Serial parsing costs a little speed and
    # removes the spike; the per-query cap keeps any single insert well under
    # the server limit.
    INSERT_SETTINGS = {
        "input_format_parallel_parsing": "0",
        "max_insert_threads": "1",
        "max_memory_usage": str(1 * 1024 ** 3),
    }

    def execute(self, sql: str, body: bytes | None = None, retries: int = 4) -> str:
        """Run a statement. Transient transport failures (a dropped connection
        mid-upload, a broken pipe) are retried with backoff; a 20M-row load
        should not lose minutes of work to one hiccup. Server-side errors are
        not retried: they mean the data or the SQL is wrong."""
        qs = {"query": sql}
        if sql.lstrip().upper().startswith("INSERT"):
            qs.update(self.INSERT_SETTINGS)
        params = urllib.parse.urlencode(qs)
        delay = 1.0
        for attempt in range(retries + 1):
            req = urllib.request.Request(f"{self.url}/?{params}", data=body or b"", method="POST")
            req.add_header("X-ClickHouse-User", self.user)
            req.add_header("X-ClickHouse-Key", self.password)
            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    return resp.read().decode()
            except urllib.error.HTTPError as e:
                raise RuntimeError(f"ClickHouse error: {e.read().decode()[:600]}") from None
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
                if attempt >= retries:
                    raise RuntimeError(f"ClickHouse unreachable after {retries} retries: {e}") from None
                print(f"    transport error ({e}); retrying in {delay:.0f}s", flush=True)
                time.sleep(delay)
                delay *= 2
        raise RuntimeError("unreachable")


CHUNK = 50_000  # rows per INSERT; keeps memory flat at 20M rows


def check_headers(path: Path, required: list[str]) -> list[str]:
    with path.open(newline="") as fh:
        headers = next(csv.reader(fh), [])
    missing = [c for c in required if c not in headers]
    if missing:
        raise SystemExit(
            f"FATAL {path.name}: missing required column(s): {', '.join(missing)}\n"
            f"  found: {', '.join(headers)}\n"
            f"  Update TABLES in scripts/load_dataset.py to map the real headers."
        )
    return headers


def stream_load(ch: "ClickHouse", table: str, path: Path, required: list[str]) -> dict:
    """Validate and insert in chunks, never holding the file in memory.

    Nothing per-row is retained. Duplicate ids are counted in ClickHouse after
    the load (see `duplicate_ids`): holding 20M id strings in a Python set was
    several hundred MB and got the process killed on a laptop alongside Docker.
    """
    headers = check_headers(path, required)
    nulls = {c: 0 for c in required}
    rows = 0
    cols = ",".join(required)

    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        batch: list[dict] = []
        for r in reader:
            rows += 1
            for c in required:
                if not (r.get(c) or "").strip():
                    nulls[c] += 1
            batch.append(r)
            if len(batch) >= CHUNK:
                ch.execute(f"INSERT INTO {DB}.{table} ({cols}) FORMAT TabSeparated",
                           to_tsv(batch, required, table))
                batch.clear()
                if rows % (CHUNK * 10) == 0:
                    print(f"    {table}: {rows:,} rows...", flush=True)
        if batch:
            ch.execute(f"INSERT INTO {DB}.{table} ({cols}) FORMAT TabSeparated",
                       to_tsv(batch, required, table))

    dupes = duplicate_ids(ch, table, required[0]) if rows else 0
    bad = dupes + sum(nulls.values())
    return {
        "file": path.name, "rows": rows, "columns": len(headers),
        "unexpected_columns": [c for c in headers if c not in required],
        "duplicate_ids": dupes,
        "null_counts": {k: v for k, v in nulls.items() if v},
        "valid_pct": round(100.0 * (1 - bad / (rows * len(required))), 3) if rows else 100.0,
    }


def reclaim_memory(ch: "ClickHouse") -> None:
    """Hand retained memory back between large tables.

    A bulk load leaves the allocator holding arenas and the caches full; the
    next table's first insert then trips the server's total-memory ceiling.
    Purging is cheap and is the difference between finishing and dying at
    the last table.
    """
    for stmt in ("SYSTEM JEMALLOC PURGE", "SYSTEM DROP MARK CACHE", "SYSTEM DROP UNCOMPRESSED CACHE"):
        try:
            ch.execute(stmt)
        except RuntimeError as e:
            # Older servers lack JEMALLOC PURGE; the cache drops still help.
            if "JEMALLOC" not in stmt:
                raise
            print(f"    ({stmt} unsupported: {str(e)[:60]})", flush=True)


def wait_for_merges(ch: "ClickHouse", timeout_s: int = 600) -> None:
    """Block until the database has no background merges in flight.

    Loading reconciliation while transactions was still merging its 20M rows is
    what pushed the server over its memory limit. A pause here is cheaper than
    a crash five minutes into the load.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        n = int(ch.execute(f"SELECT count() FROM system.merges WHERE database = '{DB}'").strip() or 0)
        if n == 0:
            return
        print(f"    waiting for {n} background merge(s) to finish...", flush=True)
        time.sleep(5)


def duplicate_ids(ch: "ClickHouse", table: str, id_col: str) -> int:
    """Rows minus distinct ids, computed where the data already is."""
    out = ch.execute(f"SELECT count() - uniqExact({id_col}) FROM {DB}.{table}")
    return int(out.strip() or 0)


def referential_checks(ch: "ClickHouse", loaded: set[str]) -> list[str]:
    """Orphan detection in SQL. The database already holds every row; asking it
    is both faster and the only approach that survives 20M records."""
    problems = []
    checks = [
        ("transactions", "vendor_id", "vendors", "vendor_id"),
        ("transactions", "account_code", "accounts", "account_code"),
        ("vendor_payouts", "vendor_id", "vendors", "vendor_id"),
        ("reconciliation", "transaction_id", "transactions", "transaction_id"),
    ]
    for table, col, ref, ref_col in checks:
        if table not in loaded or ref not in loaded:
            continue
        sql = (f"SELECT count(), any({col}) FROM {DB}.{table} "
               f"WHERE {col} != '' AND {col} NOT IN (SELECT {ref_col} FROM {DB}.{ref})")
        # A zero count comes back as "0" with an empty second column, which
        # ClickHouse serialises without a trailing tab. Parse defensively.
        parts = ch.execute(sql).strip().split("\t")
        n = int(parts[0] or 0)
        sample = parts[1] if len(parts) > 1 else ""
        if n:
            problems.append(f"{table}.{col}: {n:,} value(s) not present in {ref} "
                            f"(e.g. {sample})")
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
    ap.add_argument("--report-only", action="store_true",
                    help="skip loading; compute the quality report from the rows already "
                         "in the database (counts, nulls, duplicates, referential checks)")
    ap.add_argument("--db", default="tbx_finance",
                    help="target database. Use a sibling (e.g. tbx_finance_scale) so a "
                         "large test load never truncates the live dataset")
    args = ap.parse_args()
    global DB
    DB = args.db

    raw = Path(args.raw)
    ch = ClickHouse(args.url, args.user, args.password)
    ch.execute(f"CREATE DATABASE IF NOT EXISTS {DB}")
    # The DDL names tbx_finance literally; rewrite it for a sibling database so
    # the same schema lands wherever the load is targeted.
    schema = Path("infra/clickhouse/001_schema.sql").read_text().replace("tbx_finance", DB)
    for stmt in [s.strip() for s in schema.split(";") if s.strip()]:
        ch.execute(stmt)

    reports = []
    counts: dict[str, int] = {}
    hasher = hashlib.sha256()
    started = time.perf_counter()

    if args.report_only:
        for table in LOAD_ORDER:
            _, required = TABLES[table]
            rows = int(ch.execute(f"SELECT count() FROM {DB}.{table}").strip() or 0)
            if not rows:
                continue
            null_sql = ", ".join(f"countIf(toString({c}) = '') AS n_{i}" for i, c in enumerate(required))
            null_vals = [int(x or 0) for x in ch.execute(f"SELECT {null_sql} FROM {DB}.{table}").strip().split("\t")]
            nulls = {c: v for c, v in zip(required, null_vals) if v}
            dupes = duplicate_ids(ch, table, required[0])
            bad = dupes + sum(nulls.values())
            reports.append({"file": TABLES[table][0], "rows": rows, "columns": len(required),
                            "unexpected_columns": [], "duplicate_ids": dupes, "null_counts": nulls,
                            "valid_pct": round(100.0 * (1 - bad / (rows * len(required))), 3)})
            counts[table] = rows
            print(f"  in db  {table:16} {rows:>12,} rows   valid {reports[-1]['valid_pct']}%")

    for table in ([] if args.report_only else LOAD_ORDER):
        fname, required = TABLES[table]
        path = raw / fname
        if not path.exists():
            print(f"  skip {fname} (not present)")
            continue
        # Hash in chunks too; reading a 3GB file into memory for a checksum
        # would defeat the point of streaming the load.
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                hasher.update(block)

        if args.truncate:
            ch.execute(f"TRUNCATE TABLE IF EXISTS {DB}.{table}")
        report = stream_load(ch, table, path, required)
        reports.append(report)
        counts[table] = report["rows"]
        print(f"  loaded {table:16} {report['rows']:>12,} rows   valid {report['valid_pct']}%")
        if report["rows"] >= 1_000_000:
            wait_for_merges(ch)
            reclaim_memory(ch)

    problems = referential_checks(ch, set(counts))
    elapsed = time.perf_counter() - started
    print(f"\n  load time {elapsed:,.1f}s")
    version = args.version or f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    checksum = hasher.hexdigest()[:16]

    if not args.report_only:
      ch.execute(
        f"INSERT INTO {DB}.dataset_versions "
        "(dataset_version, loaded_at, source_files, row_counts, checksum) FORMAT TabSeparated",
        to_tsv([{
            "dataset_version": version,
            "loaded_at": f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}",
            "source_files": ",".join(sorted(f for f, _ in TABLES.values())),
            "row_counts": json.dumps(counts),
            "checksum": checksum,
        }], ["dataset_version", "loaded_at", "source_files", "row_counts", "checksum"]),
      )

    out = {
        "dataset_version": version, "checksum": checksum,
        "tables": reports, "referential_problems": problems,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "load_seconds": round(elapsed, 1),
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
