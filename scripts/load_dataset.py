#!/usr/bin/env python3
"""Load CSVs from data/raw into ClickHouse, with validation and a quality report.

TABLES is the only schema source; a file missing a required column aborts the load.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from app.services.crypto import FieldCipher  # noqa: E402
from app.services.narration import parse_narration  # noqa: E402

DB = "tbx_finance"
"""Overridden by --db; the scale test loads into a sibling database."""

TABLES: dict[str, tuple[str, list[str]]] = {
    "bank": ("bank.csv", ["bank_code", "bank_name"]),
    "account": ("account.csv",
                ["account_id", "entity_id", "account_number", "program_id",
                 "available_balance", "bank_code"]),
    "transaction": ("transaction.csv",
                    ["transaction_id", "account_id", "transaction_date", "transaction_type",
                     "description", "transaction_amount", "transaction_reference_id",
                     "utr_number"]),
}

LOAD_ORDER = ["bank", "account", "transaction"]

INSERT_COLUMNS: dict[str, list[str]] = {
    "bank": ["bank_code", "bank_name"],
    "account": ["account_id", "entity_id", "account_number_enc", "account_last4", "program_id",
                "available_balance", "bank_code"],
    "transaction": ["transaction_id", "account_id", "entity_id", "bank_code", "transaction_date",
                    "transaction_type", "description", "counterparty", "channel",
                    "transaction_amount", "transaction_reference_id", "utr_enc", "utr_hash"],
}
"""What actually goes into ClickHouse: the CSV columns with plaintext sensitive fields
replaced by their encrypted form and blind index, plus derived columns."""

ACCOUNT_OWNER: dict[str, tuple[str, str]] = {}


class ClickHouse:
    def __init__(self, url: str, user: str, password: str):
        self.url, self.user, self.password = url.rstrip("/"), user, password

    INSERT_SETTINGS = {
        "input_format_parallel_parsing": "0",
        "max_insert_threads": "1",
        "max_memory_usage": str(1 * 1024 ** 3),
    }
    """Serial parsing plus a per-query cap: parallel parsing alongside background merges
    exceeded the container's memory at 20M rows."""

    def execute(self, sql: str, body: bytes | None = None, retries: int = 4) -> str:
        """Run a statement. Transport failures are retried with backoff; server errors are not."""
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


CHUNK = 50_000
"""Rows per INSERT."""


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


CIPHER: FieldCipher | None = None


def transform(table: str, r: dict) -> None:
    """Encrypt sensitive fields, add blind indexes and derived columns, in place."""
    assert CIPHER is not None
    if table == "account":
        number = (r.get("account_number") or "").strip()
        r["account_number_enc"] = CIPHER.encrypt(number)
        r["account_last4"] = number[-4:]
        r["account_number"] = ""
    elif table == "transaction":
        r["entity_id"], r["bank_code"] = ACCOUNT_OWNER.get(r["account_id"], ("", ""))
        utr = (r.get("utr_number") or "").strip()
        r["utr_enc"] = CIPHER.encrypt(utr)
        r["utr_hash"] = CIPHER.blind_index(utr)
        r["utr_number"] = ""
        r["counterparty"], r["channel"] = parse_narration(r.get("description") or "")


def load_account_owner(ch: "ClickHouse") -> None:
    if ACCOUNT_OWNER:
        return
    for line in ch.execute(f"SELECT account_id, entity_id, bank_code FROM {DB}.account FINAL").splitlines():
        aid, eid, bc = line.split("\t")
        ACCOUNT_OWNER[aid] = (eid, bc)
    if not ACCOUNT_OWNER:
        raise SystemExit("account is empty; load account.csv before transaction.csv")


def stream_load(ch: "ClickHouse", table: str, path: Path, required: list[str]) -> dict:
    """Validate and insert in chunks without holding the file in memory.

    Duplicate ids are counted in ClickHouse afterwards (`duplicate_ids`); a Python set of
    20M ids was several hundred MB.
    """
    headers = check_headers(path, required)
    nulls = {c: 0 for c in required}
    rows = 0
    out_cols = INSERT_COLUMNS[table]
    cols = ",".join(out_cols)
    if table == "transaction":
        load_account_owner(ch)

    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        batch: list[dict] = []
        for r in reader:
            rows += 1
            for c in required:
                if not (r.get(c) or "").strip() and c not in EMPTY_OK.get(table, ()):
                    nulls[c] += 1
            transform(table, r)
            batch.append(r)
            if len(batch) >= CHUNK:
                ch.execute(f"INSERT INTO {DB}.{table} ({cols}) FORMAT TabSeparated",
                           to_tsv(batch, out_cols, table))
                batch.clear()
                if rows % (CHUNK * 10) == 0:
                    print(f"    {table}: {rows:,} rows...", flush=True)
        if batch:
            ch.execute(f"INSERT INTO {DB}.{table} ({cols}) FORMAT TabSeparated",
                       to_tsv(batch, out_cols, table))

    if table == "account":
        ACCOUNT_OWNER.clear()

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
    """Purge allocator arenas and caches between large tables.

    Without this the next table's first insert trips the server's total-memory ceiling.
    Older servers lack JEMALLOC PURGE; the cache drops still help.
    """
    for stmt in ("SYSTEM JEMALLOC PURGE", "SYSTEM DROP MARK CACHE", "SYSTEM DROP UNCOMPRESSED CACHE"):
        try:
            ch.execute(stmt)
        except RuntimeError as e:
            if "JEMALLOC" not in stmt:
                raise
            print(f"    ({stmt} unsupported: {str(e)[:60]})", flush=True)


def wait_for_merges(ch: "ClickHouse", timeout_s: int = 600) -> None:
    """Block until no background merges are in flight.

    Loading the next table while transactions was still merging 20M rows exceeded the
    server's memory limit.
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
    """Orphan detection in SQL, which is the only approach that survives 20M records.

    A zero count is serialised as "0" with no trailing tab, so the second column may be absent.
    """
    problems = []
    checks = [
        ("account", "bank_code", "bank", "bank_code"),
        ("transaction", "account_id", "account", "account_id"),
    ]
    for table, col, ref, ref_col in checks:
        if table not in loaded or ref not in loaded:
            continue
        sql = (f"SELECT count(), any({col}) FROM {DB}.{table} "
               f"WHERE {col} != '' AND {col} NOT IN (SELECT {ref_col} FROM {DB}.{ref})")
        parts = ch.execute(sql).strip().split("\t")
        n = int(parts[0] or 0)
        sample = parts[1] if len(parts) > 1 else ""
        if n:
            problems.append(f"{table}.{col}: {n:,} value(s) not present in {ref} "
                            f"(e.g. {sample})")
    return problems


NULLABLE_COLUMNS: dict[str, set[str]] = {}

EMPTY_OK: dict[str, set[str]] = {
    "transaction": {"transaction_reference_id", "utr_number", "description"},
}
"""Columns the schema declares DEFAULT NULL; an empty cell is not a quality defect."""
"""Columns declared Nullable in the schema; an empty cell becomes the TabSeparated \\N marker
because an empty string will not parse as a DateTime."""


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
    global CIPHER
    CIPHER = FieldCipher.from_env()

    raw = Path(args.raw)
    ch = ClickHouse(args.url, args.user, args.password)
    ch.execute(f"CREATE DATABASE IF NOT EXISTS {DB}")
    schema = Path("infra/clickhouse/001_schema.sql").read_text().replace("tbx_finance", DB)
    schema = "\n".join(line.split("--", 1)[0] for line in schema.splitlines())
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
