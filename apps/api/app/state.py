"""Process-wide singletons, built once at startup."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from threading import Lock

from .agents.judge import Judge
from .agents.pipeline import ConversationState, DatasetContext, Pipeline
from .contracts.plan import FinanceQueryPlan
from .services.cache import Cache
from .config.settings import settings
from .db.clickhouse import ClickHouseClient
from .llm.router import ModelRouter
from .services.dates import DatasetCalendar
from .services.ingest import IngestRunner
from .services.mysql_source import MySQLTarget
from .services.resolver import AccountRecord, CounterpartyRecord
from .services.source_mapping import SourceMapping

log = logging.getLogger("tbx.state")


CONVERSATION_TTL = int(os.getenv("SESSION_TTL_SECONDS", "14400"))


@dataclass
class AppState:
    """Process singletons. `usage_log` is a ring buffer of per-run accounting for /admin/usage."""
    ch: ClickHouseClient | None = None
    router: ModelRouter | None = None
    ctx: DatasetContext | None = None
    cache: Cache | None = None
    judge: Judge | None = None
    conversations: dict[str, ConversationState] = field(default_factory=dict)
    ingest: IngestRunner = field(default_factory=IngestRunner)
    source: MySQLTarget | None = None
    """The user-supplied MySQL endpoint currently backing the dataset, if any."""
    pending_sources: dict[str, tuple[MySQLTarget, SourceMapping]] = field(default_factory=dict)
    """Validated-but-not-yet-initialised connections, keyed by the token handed to
    the Data Source page. In memory only; credentials are never persisted."""
    usage_log: list[dict] = field(default_factory=list)
    max_usage_log: int = 2000
    _lock: Lock = field(default_factory=Lock)

    def record_run(self, response) -> None:
        """Append run accounting; other_ms covers resolution, compilation, verification and
        composition."""
        from datetime import datetime, timezone
        calls = response.model_usage or []
        llm_ms = round(sum(c.get("duration_ms", 0) for c in calls), 1)
        query_ms = (response.evidence.query_duration_ms or 0) if response.evidence else 0
        total = response.duration_ms or 0
        models = [c["model"].split("/")[-1] for c in calls if c.get("ok")]
        with self._lock:
            self.usage_log.append({
                "run_id": response.run_id,
                "state": response.state.value,
                "duration_ms": total,
                "llm_ms": llm_ms,
                "query_ms": round(query_ms, 1),
                "other_ms": round(max(0.0, total - llm_ms - query_ms), 1),
                "tokens": sum(c.get("prompt_tokens", 0) + c.get("completion_tokens", 0) for c in calls),
                "model": models[0] if models else None,
                "switched": len(set(models)) > 1,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "calls": calls,
            })
            if len(self.usage_log) > self.max_usage_log:
                del self.usage_log[: len(self.usage_log) - self.max_usage_log]

    def clear_history(self) -> dict[str, int]:
        """Drop per-run accounting, judge verdicts and every conversation, in memory and in
        Redis. Plan and answer caches and circuit breakers are kept: they are performance
        state, not history."""
        with self._lock:
            runs = len(self.usage_log)
            conversations = len(self.conversations)
            self.usage_log.clear()
            self.conversations.clear()
        removed = 0
        if self.cache:
            removed += self.cache.delete_prefix("conv")
            removed += self.cache.delete_prefix("judge")
        return {"runs": runs, "conversations": conversations, "redis_keys": removed}

    @property
    def ready(self) -> bool:
        return self.ch is not None and self.ctx is not None

    def pipeline(self, on_event=None) -> Pipeline:
        assert self.ready, "app state not initialised"
        return Pipeline(self.ch, self.router, self.ctx, on_event=on_event, judge=self.judge)

    def conversation(self, conversation_id: str) -> ConversationState:
        """Conversation state lives in Redis, with the in-memory dict as the fallback."""
        with self._lock:
            st = self.conversations.get(conversation_id)
            if st is not None:
                return st
            doc = self.cache.get_json("conv", conversation_id) if self.cache else None
            st = ConversationState(conversation_id=conversation_id)
            if doc:
                st.turns = int(doc.get("turns", 0))
                st.last_period_label = doc.get("last_period_label")
                st.pending_question = doc.get("pending_question")
                st.pending_field = doc.get("pending_field")
                st.entity_id = doc.get("entity_id")
                for field in ("last_plan", "pending_plan"):
                    if doc.get(field):
                        try:
                            setattr(st, field, FinanceQueryPlan.model_validate(doc[field]))
                        except Exception:  # noqa: BLE001
                            pass
            self.conversations[conversation_id] = st
            return st

    def save_conversation(self, st: ConversationState) -> None:
        if not self.cache:
            return
        self.cache.set_json("conv", st.conversation_id, value={
            "turns": st.turns, "last_period_label": st.last_period_label,
            "pending_question": st.pending_question,
            "pending_field": st.pending_field,
            "entity_id": st.entity_id,
            "last_plan": st.last_plan.model_dump(mode="json") if st.last_plan else None,
            "pending_plan": st.pending_plan.model_dump(mode="json") if st.pending_plan else None,
        }, ttl=CONVERSATION_TTL)


app_state = AppState()


MAX_COUNTERPARTIES = int(os.getenv("TBX_MAX_COUNTERPARTIES", "5000"))
"""Distinct counterparties kept in memory for resolution, most active first."""


def build_dataset_context(ch: ClickHouseClient) -> DatasetContext:
    """Read bounds, counterparties, accounts, banks and entities from ClickHouse so date
    resolution and name matching follow the loaded data."""
    bounds = ch.query(
        "SELECT min(txn_date) AS lo, max(txn_date) AS hi, count() AS n "
        "FROM tbx_finance.transaction").rows[0]
    if not bounds or int(bounds.get("n", 0)) == 0:
        raise RuntimeError("no transactions loaded; run scripts/load_dataset.py first")

    banks = {r["bank_code"]: r["bank_name"] for r in
             ch.query("SELECT bank_code, bank_name FROM tbx_finance.bank FINAL").rows}
    accounts = [
        AccountRecord(r["account_id"], r["entity_id"], r["account_last4"], r["bank_code"],
                      banks.get(r["bank_code"], r["bank_code"]), int(r["program_id"]),
                      float(r["available_balance"]))
        for r in ch.query(
            "SELECT account_id, entity_id, account_last4, bank_code, program_id, "
            "available_balance FROM tbx_finance.account FINAL").rows
    ]
    counterparties = [
        CounterpartyRecord(r["counterparty"], int(r["n"]), r["channel"],
                           frozenset(r["entities"]))
        for r in ch.query(
            "SELECT counterparty, count() AS n, topK(1)(channel)[1] AS channel, "
            "groupUniqArray(entity_id) AS entities FROM tbx_finance.transaction "
            "WHERE counterparty != '' GROUP BY counterparty ORDER BY n DESC "
            "LIMIT {lim:UInt32}", {"lim": MAX_COUNTERPARTIES}).rows
    ]
    entity_rows = ch.query(
        "SELECT entity_id, count() AS n FROM tbx_finance.transaction "
        "GROUP BY entity_id ORDER BY n DESC").rows
    entities = [r["entity_id"] for r in entity_rows]
    default_entity = os.getenv("TBX_DEFAULT_ENTITY") or (entities[0] if entities else None)
    version_rows = ch.query(
        "SELECT dataset_version FROM tbx_finance.dataset_versions "
        "ORDER BY loaded_at DESC LIMIT 1").rows
    version = version_rows[0]["dataset_version"] if version_rows else settings.dataset_version
    log.info("dataset %s: %s..%s, %s transactions, %d accounts, %d counterparties, %d entities",
             version, bounds["lo"], bounds["hi"], bounds["n"], len(accounts),
             len(counterparties), len(entities))
    return DatasetContext(
        calendar=DatasetCalendar(min_date=date.fromisoformat(str(bounds["lo"])),
                                 max_date=date.fromisoformat(str(bounds["hi"]))),
        counterparties=counterparties, accounts=accounts, banks=banks, entities=entities,
        currency="INR", dataset_version=version, default_entity=default_entity)


def rebuild_dataset_context() -> None:
    """Re-read the dataset facts after an ingest replaces the tables.

    The judge is rebuilt with the new dataset version so cached plans and answers
    from the previous dataset can never be served against the new one.
    """
    assert app_state.ch is not None, "app state not initialised"
    app_state.ctx = build_dataset_context(app_state.ch)
    if app_state.cache is not None:
        app_state.judge = Judge(app_state.cache, app_state.ctx.dataset_version)
        if app_state.router is not None:
            app_state.router.judge = app_state.judge
    app_state.conversations.clear()


def startup() -> None:
    """Build the singletons; a non-compliant configured model stops the service here."""
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
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
        from stub_llm import stub_completion  # type: ignore
        completion_fn = stub_completion
        log.warning("TBX_USE_STUB_LLM=1 -- using the offline stub planner, NOT a real model")

    app_state.cache = Cache(settings.redis_url)
    app_state.judge = Judge(app_state.cache, app_state.ctx.dataset_version)
    router = ModelRouter(completion_fn=completion_fn, timeout=settings.llm_timeout,
                         judge=app_state.judge)
    if completion_fn is None:
        from .llm.catalog import check_compliance
        for warning in check_compliance(router.configured_models()):
            log.warning(warning)
    app_state.router = router
