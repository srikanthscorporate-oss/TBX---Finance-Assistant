"""Process-wide singletons, built once at startup."""
from __future__ import annotations

import csv
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from threading import Lock

from .agents.pipeline import ConversationState, DatasetContext, Pipeline
from .config.settings import settings
from .db.clickhouse import ClickHouseClient
from .llm.router import ModelRouter
from .services.dates import DatasetCalendar
from .services.resolver import VendorRecord

log = logging.getLogger("tbx.state")


@dataclass
class AppState:
    ch: ClickHouseClient | None = None
    router: ModelRouter | None = None
    ctx: DatasetContext | None = None
    conversations: dict[str, ConversationState] = field(default_factory=dict)
    # Ring buffer of per-run accounting. Feeds /admin/usage, which is how the
    # model-efficiency claims are evidenced rather than asserted.
    usage_log: list[dict] = field(default_factory=list)
    max_usage_log: int = 2000
    _lock: Lock = field(default_factory=Lock)

    def record_run(self, response) -> None:
        with self._lock:
            self.usage_log.append({
                "run_id": response.run_id,
                "state": response.state.value,
                "duration_ms": response.duration_ms,
                "calls": response.model_usage,
            })
            if len(self.usage_log) > self.max_usage_log:
                del self.usage_log[: len(self.usage_log) - self.max_usage_log]

    @property
    def ready(self) -> bool:
        return self.ch is not None and self.ctx is not None

    def pipeline(self, on_event=None) -> Pipeline:
        assert self.ready, "app state not initialised"
        return Pipeline(self.ch, self.router, self.ctx, on_event=on_event)

    def conversation(self, conversation_id: str) -> ConversationState:
        with self._lock:
            st = self.conversations.get(conversation_id)
            if st is None:
                st = ConversationState(conversation_id=conversation_id)
                self.conversations[conversation_id] = st
            return st


app_state = AppState()


def build_dataset_context(ch: ClickHouseClient) -> DatasetContext:
    """Read the dataset's own bounds, vendor list and categories from ClickHouse.

    Loading these from the database (not a config file) is what keeps date
    resolution anchored to whatever data is actually loaded.
    """
    bounds = ch.query(
        "SELECT min(txn_date) AS lo, max(txn_date) AS hi, count() AS n "
        "FROM tbx_finance.transactions").rows[0]
    if not bounds or int(bounds.get("n", 0)) == 0:
        raise RuntimeError("no transactions loaded; run scripts/load_dataset.py first")

    vendors = [
        VendorRecord(r["vendor_id"], r["vendor_name"], r.get("legal_name", ""),
                     r.get("category", ""), r.get("status", "active"))
        for r in ch.query(
            "SELECT vendor_id, vendor_name, legal_name, category, status "
            "FROM tbx_finance.vendors").rows
    ]
    categories = [r["category"] for r in ch.query(
        "SELECT DISTINCT category FROM tbx_finance.transactions ORDER BY category").rows]
    currency_rows = ch.query(
        "SELECT currency, count() AS n FROM tbx_finance.transactions "
        "GROUP BY currency ORDER BY n DESC LIMIT 1").rows
    currency = currency_rows[0]["currency"] if currency_rows else "USD"

    version_rows = ch.query(
        "SELECT dataset_version FROM tbx_finance.dataset_versions "
        "ORDER BY loaded_at DESC LIMIT 1").rows
    version = version_rows[0]["dataset_version"] if version_rows else settings.dataset_version

    log.info("dataset %s: %s..%s, %s transactions, %d vendors, currency=%s",
             version, bounds["lo"], bounds["hi"], bounds["n"], len(vendors), currency)

    return DatasetContext(
        calendar=DatasetCalendar(min_date=date.fromisoformat(str(bounds["lo"])),
                                 max_date=date.fromisoformat(str(bounds["hi"]))),
        vendors=vendors, categories=categories, currency=currency,
        dataset_version=version)


def startup() -> None:
    ch = ClickHouseClient(
        host=settings.ch_host, port=settings.ch_port, user=settings.ch_user,
        password=settings.ch_password, database=settings.ch_db,
        timeout=settings.query_timeout, max_result_rows=50_000)
    if not ch.ping():
        raise RuntimeError(f"ClickHouse unreachable at {settings.ch_host}:{settings.ch_port}")

    app_state.ch = ch
    app_state.ctx = build_dataset_context(ch)

    completion_fn = None
    if os.getenv("TBX_USE_STUB_LLM") == "1":
        # Offline demo mode: lets the whole product be shown without an API key.
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
        from stub_llm import stub_completion  # type: ignore
        completion_fn = stub_completion
        log.warning("TBX_USE_STUB_LLM=1 -- using the offline stub planner, NOT a real model")

    app_state.router = ModelRouter(completion_fn=completion_fn,
                                   timeout=settings.llm_timeout)
