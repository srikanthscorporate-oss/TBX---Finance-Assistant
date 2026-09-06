"""Ingest a mapped MySQL source into the canonical ClickHouse schema.

This is the "Start Initializing" step. It replaces the contents of the canonical
tables with the user's data, so from then on every answer the assistant gives is
computed from their endpoint -- through the same planner, compiler, verification
and evidence path as before. Nothing downstream of ClickHouse changes, which is
the point: the grounding guarantees are not re-implemented for a new source.

Writes go through the ClickHouse *admin* user over HTTP; the agent user the
query path uses stays read-only.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ..config.settings import settings
from . import mysql_source as ms
from .active_db import check_name, source_db_name
from .crypto import FieldCipher
from .narration import parse_narration
from .source_mapping import DEFAULTS, SourceMapping, TableMapping

log = logging.getLogger("tbx.ingest")

INSERT_COLUMNS: dict[str, list[str]] = {
    "bank": ["bank_code", "bank_name"],
    "account": ["account_id", "entity_id", "account_number_enc", "account_last4", "program_id",
                "available_balance", "bank_code"],
    "transaction": ["transaction_id", "account_id", "entity_id", "bank_code", "transaction_date",
                    "transaction_type", "description", "counterparty", "channel",
                    "transaction_amount", "transaction_reference_id", "utr_enc", "utr_hash"],
}
"""Mirrors scripts/load_dataset.py: the CSV path and this path must produce
identical rows, or a figure would depend on how the data arrived."""

CHUNK = 20_000

_CREDIT = {"c", "cr", "credit", "+", "in", "inward", "deposit", "receipt", "income"}
_DEBIT = {"d", "dr", "debit", "-", "out", "outward", "withdrawal", "payment", "expense"}


class IngestError(RuntimeError):
    pass


class ClickHouseWriter:
    """Minimal admin-credentialed HTTP writer. Read queries still go through
    app.db.clickhouse as the read-only user."""

    def __init__(self, url: str, user: str, password: str, timeout: int = 300):
        self.url, self.user, self.password, self.timeout = url.rstrip("/"), user, password, timeout

    def execute(self, sql: str, body: bytes | None = None) -> str:
        params = urllib.parse.urlencode({"query": sql})
        req = urllib.request.Request(f"{self.url}/?{params}", data=body or b"", method="POST")
        req.add_header("X-ClickHouse-User", self.user)
        req.add_header("X-ClickHouse-Key", self.password)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.read().decode()
        except urllib.error.HTTPError as e:
            raise IngestError(f"ClickHouse rejected the statement: {e.read().decode()[:400]}") from None
        except (urllib.error.URLError, OSError) as e:
            raise IngestError(f"ClickHouse unreachable: {e}") from None


@dataclass
class IngestProgress:
    """Snapshot polled by the Data Source page while initialisation runs."""

    state: str = "idle"
    """idle | running | loaded | ready | failed. `loaded` is the gap between the last
    insert and the assistant re-reading the dataset; the page treats it as running."""
    step: str = ""
    tables: dict[str, int] = field(default_factory=dict)
    totals: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    dataset_version: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    warnings: list[str] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        done = sum(self.tables.values())
        total = sum(self.totals.values()) or 0
        return {
            "state": self.state, "step": self.step,
            "rows_loaded": self.tables, "rows_expected": self.totals,
            "percent": round(100.0 * done / total, 1) if total else (100.0 if self.state == "ready" else 0.0),
            "busy": self.state in ("running", "loaded"),
            "error": self.error, "dataset_version": self.dataset_version,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "warnings": list(self.warnings),
        }


def _schema_statements() -> list[str]:
    """DDL from the one schema file, so the ingested shape cannot drift from it."""
    here = Path(__file__).resolve()
    for base in (Path("/srv"), *here.parents, Path.cwd()):
        path = base / "infra" / "clickhouse" / "001_schema.sql"
        if path.exists():
            text = "\n".join(line.split("--", 1)[0] for line in path.read_text().splitlines())
            return [s.strip() for s in text.split(";") if s.strip()]
    return []


def _decimal(value: Any, *, field_name: str) -> Decimal:
    """Amounts and balances are parsed strictly. A value that is not a number is a
    hard failure, never a zero: a silent zero is a fabricated figure."""
    if value is None or value == "":
        raise IngestError(f"{field_name} is empty in the source; it must be a number")
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise IngestError(f"{field_name} is not a number in the source: {value!r}") from None


def _datetime(value: Any) -> str:
    if value is None or value == "":
        raise IngestError("transaction_date is empty in the source")
    text = str(value).strip().replace("T", " ")
    if len(text) == 10:
        text += " 00:00:00"
    return text[:26]


def _direction(raw: Any, amount: Decimal, from_sign: bool) -> tuple[str, Decimal]:
    """Return (transaction_type, non-negative amount).

    With no direction column the sign of the amount is the direction -- arithmetic
    on the source value, not an inference about it.
    """
    if from_sign or raw in (None, ""):
        return ("debit", -amount) if amount < 0 else ("credit", amount)
    token = str(raw).strip().lower()
    if token in _CREDIT:
        return "credit", abs(amount)
    if token in _DEBIT:
        return "debit", abs(amount)
    if token in ("credit", "debit"):
        return token, abs(amount)
    return ("debit", -amount) if amount < 0 else ("credit", amount)


def _tsv(rows: list[dict[str, Any]], columns: list[str]) -> bytes:
    out = []
    for r in rows:
        fields = []
        for c in columns:
            v = r.get(c)
            v = "" if v is None else str(v)
            fields.append(v.replace("\\", "\\\\").replace("\t", " ").replace("\n", " "))
        out.append("\t".join(fields))
    return ("\n".join(out) + "\n").encode()


class Ingestor:
    """One initialisation run. Not reused; a second run builds a new instance."""

    def __init__(self, target: ms.MySQLTarget, mapping: SourceMapping, *,
                 db: str | None = None, on_progress: Callable[[], None] | None = None):
        self.target = target
        self.mapping = mapping
        # A sibling of the bundled database, never the bundled one: the test suite
        # and every verify gate recompute the bundled tables from data/raw.
        self.db = check_name(db) if db else source_db_name()
        self.progress = IngestProgress()
        self.cipher = FieldCipher.from_env()
        self.on_progress = on_progress
        self._owner: dict[str, tuple[str, str]] = {}
        self._bank_codes: set[str] = set()

    # -- plumbing ---------------------------------------------------------
    def _tick(self, step: str | None = None) -> None:
        if step:
            self.progress.step = step
        if self.on_progress:
            self.on_progress()

    def _writer(self) -> ClickHouseWriter:
        return ClickHouseWriter(
            f"http://{settings.ch_host}:{settings.ch_port}",
            settings.ch_admin_user, settings.ch_admin_password)

    # -- the run ----------------------------------------------------------
    def run(self) -> IngestProgress:
        p = self.progress
        p.state = "running"
        p.started_at = datetime.now(UTC).isoformat(timespec="seconds")
        p.totals = {name: m.rows for name, m in self.mapping.tables.items() if m.usable}
        try:
            ch = self._writer()
            self._tick("preparing the canonical schema")
            ch.execute(f"CREATE DATABASE IF NOT EXISTS {self.db}")
            for stmt in _schema_statements():
                ch.execute(stmt.replace("tbx_finance", self.db))
            # The query path connects as the read-only agent user, which is granted
            # the bundled database only; a sibling needs its own SELECT grant.
            ch.execute(f"GRANT SELECT ON {self.db}.* TO tbx_readonly")

            conn = ms.connect(self.target)
            try:
                for table in ("bank", "account", "transaction"):
                    m = self.mapping.tables[table]
                    if not m.usable:
                        continue
                    self._tick(f"loading {table}")
                    ch.execute(f"TRUNCATE TABLE IF EXISTS {self.db}.{table}")
                    self._load(ch, conn, table, m)
                if not self.mapping.tables["bank"].usable:
                    self._synthesise_banks(ch)
            finally:
                conn.close()

            version = f"mysql-{datetime.now(UTC):%Y%m%d-%H%M%S}"
            ch.execute(
                f"INSERT INTO {self.db}.dataset_versions "
                "(dataset_version, loaded_at, source_files, row_counts, checksum) "
                "FORMAT TabSeparated",
                _tsv([{
                    "dataset_version": version,
                    "loaded_at": f"{datetime.now(UTC):%Y-%m-%d %H:%M:%S}",
                    "source_files": f"mysql://{self.target.host}:{self.target.port}/{self.target.database}",
                    "row_counts": json.dumps(p.tables),
                    "checksum": "",
                }], ["dataset_version", "loaded_at", "source_files", "row_counts", "checksum"]))

            p.dataset_version = version
            p.state = "loaded"
            p.step = "handing the dataset to the assistant"
        except Exception as e:  # noqa: BLE001 -- every failure must reach the page
            log.error("ingest failed: %s", e)
            p.state = "failed"
            p.error = str(e)
        finally:
            p.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
            self._tick()
        return p

    def _load(self, ch: ClickHouseWriter, conn, table: str, m: TableMapping) -> None:
        assert m.source_table is not None
        source_cols = sorted(set(m.columns.values()))
        out_cols = INSERT_COLUMNS[table]
        col_list = ",".join(out_cols)
        loaded = 0
        batch: list[dict[str, Any]] = []
        for rows in ms.stream(conn, self.target.database, m.source_table, source_cols):
            for raw in rows:
                batch.append(self._row(table, m, raw))
            if len(batch) >= CHUNK:
                ch.execute(f"INSERT INTO {self.db}.{table} ({col_list}) FORMAT TabSeparated",
                           _tsv(batch, out_cols))
                loaded += len(batch)
                batch.clear()
                self.progress.tables[table] = loaded
                self._tick()
        if batch:
            ch.execute(f"INSERT INTO {self.db}.{table} ({col_list}) FORMAT TabSeparated",
                       _tsv(batch, out_cols))
            loaded += len(batch)
        self.progress.tables[table] = loaded
        self._tick()
        if table == "transaction" and loaded == 0:
            raise IngestError("the source transaction table returned no rows")

    def _get(self, m: TableMapping, raw: dict[str, Any], canonical: str) -> Any:
        src = m.columns.get(canonical)
        return raw.get(src) if src else DEFAULTS.get(canonical, "")

    def _row(self, table: str, m: TableMapping, raw: dict[str, Any]) -> dict[str, Any]:
        if table == "bank":
            code = str(self._get(m, raw, "bank_code") or "").strip().upper()
            return {"bank_code": code, "bank_name": str(self._get(m, raw, "bank_name") or code).strip()}

        if table == "account":
            account_id = str(self._get(m, raw, "account_id") or "").strip()
            if not account_id:
                raise IngestError("an account row has no account_id")
            entity = str(self._get(m, raw, "entity_id") or DEFAULTS["entity_id"]).strip()
            bank = str(self._get(m, raw, "bank_code") or DEFAULTS["bank_code"]).strip().upper()
            number = str(self._get(m, raw, "account_number") or "").strip()
            program = str(self._get(m, raw, "program_id") or "0").strip()
            self._owner[account_id] = (entity, bank)
            self._bank_codes.add(bank)
            return {
                "account_id": account_id, "entity_id": entity,
                "account_number_enc": self.cipher.encrypt(number),
                "account_last4": number[-4:] if number else account_id[-4:],
                "program_id": program if program.isdigit() else "0",
                "available_balance": f"{_decimal(self._get(m, raw, 'available_balance'), field_name='available_balance'):f}",
                "bank_code": bank,
            }

        account_id = str(self._get(m, raw, "account_id") or "").strip()
        entity, bank = self._owner.get(account_id, ("", ""))
        if not entity:
            raise IngestError(
                f"transaction references account_id {account_id!r}, which is not in the "
                "account table; the two tables must reconcile")
        amount = _decimal(self._get(m, raw, "transaction_amount"),
                          field_name="transaction_amount")
        txn_type, amount = _direction(self._get(m, raw, "transaction_type"), amount,
                                      m.derive_type_from_sign)
        description = str(self._get(m, raw, "description") or "").strip()
        parsed_name, channel = parse_narration(description)
        counterparty = str(self._get(m, raw, "counterparty") or "").strip().upper() or parsed_name
        utr = str(self._get(m, raw, "utr_number") or "").strip()
        return {
            "transaction_id": str(self._get(m, raw, "transaction_id") or "").strip(),
            "account_id": account_id, "entity_id": entity, "bank_code": bank,
            "transaction_date": _datetime(self._get(m, raw, "transaction_date")),
            "transaction_type": txn_type, "description": description,
            "counterparty": counterparty, "channel": channel,
            "transaction_amount": f"{amount:f}",
            "transaction_reference_id": str(self._get(m, raw, "transaction_reference_id") or "").strip(),
            "utr_enc": self.cipher.encrypt(utr),
            "utr_hash": self.cipher.blind_index(utr),
        }

    def _synthesise_banks(self, ch: ClickHouseWriter) -> None:
        """No bank table in the source: register the codes the accounts referenced so
        display names resolve. A code is a label, not a figure."""
        if not self._bank_codes:
            return
        ch.execute(f"TRUNCATE TABLE IF EXISTS {self.db}.bank")
        rows = [{"bank_code": c, "bank_name": c} for c in sorted(self._bank_codes)]
        ch.execute(f"INSERT INTO {self.db}.bank (bank_code,bank_name) FORMAT TabSeparated",
                   _tsv(rows, ["bank_code", "bank_name"]))
        self.progress.tables["bank"] = len(rows)
        self.progress.warnings.append(
            "No bank table was found; bank names fall back to their codes.")


class IngestRunner:
    """Serialises initialisation: one run at a time, progress readable meanwhile."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.progress = IngestProgress()

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, ingestor: Ingestor, after: Callable[[IngestProgress], None]) -> None:
        with self._lock:
            if self.busy:
                raise IngestError("an initialisation is already running")
            self.progress = ingestor.progress

            def _run() -> None:
                result = ingestor.run()
                if result.state == "loaded":
                    after(result)
                    if result.state == "loaded":
                        result.state, result.step = "ready", "ready"
                    result.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
                    if ingestor.on_progress:
                        ingestor.on_progress()

            self._thread = threading.Thread(target=_run, name="tbx-ingest", daemon=True)
            self._thread.start()
