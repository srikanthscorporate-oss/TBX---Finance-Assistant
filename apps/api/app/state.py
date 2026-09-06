"""Process-wide singletons, built once at startup."""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from threading import Lock

from .agents.judge import Judge
from .agents.pipeline import ConversationState, DatasetContext, Pipeline
from .contracts.plan import FinanceQueryPlan
from .services.cache import Cache
from .config.settings import settings
from .db.mysql import MySQLClient, MySQLTarget
from .llm.router import ModelRouter
from .services.dates import DatasetCalendar
from .services.resolver import AccountRecord, CounterpartyRecord

log = logging.getLogger("tbx.state")


CONVERSATION_TTL = int(os.getenv("SESSION_TTL_SECONDS", "14400"))


@dataclass
class AppState:
    """Process singletons. `usage_log` is a ring buffer of per-run accounting for /admin/usage."""
    ch: MySQLClient | None = None
    """Read-only client onto the live MySQL source. Keeps its historical name so the
    pipeline, data endpoints and anomaly agent are unchanged."""
    router: ModelRouter | None = None
    ctx: DatasetContext | None = None
    cache: Cache | None = None
    judge: Judge | None = None
    conversations: dict[str, ConversationState] = field(default_factory=dict)
    source: MySQLTarget | None = None
    """The MySQL endpoint the assistant is answering from."""
    pending_sources: dict[str, MySQLTarget] = field(default_factory=dict)
    """Validated-but-not-yet-connected endpoints, keyed by the token handed to the
    Data Source page. In memory only; credentials are never persisted."""
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


COUNTERPARTY_WINDOW_DAYS = int(os.getenv("TBX_COUNTERPARTY_WINDOW_DAYS", "7"))
"""How far back from the newest transaction the counterparty list is derived. The
source has no counterparty column and the link to it is slow, so the list is built
from a recent window rather than a full scan; a name outside the window still
resolves as an exact match on the derived expression at query time."""


def build_dataset_context(ch: MySQLClient) -> DatasetContext:
    """Read bounds, counterparties, accounts, banks and entities from the live source
    so date resolution and name matching follow the data actually there.

    Every statement here is bounded: min/max use the date index, accounts and banks
    are small tables, entities come from `account`, and counterparties from the recent
    window above. Nothing reads the transaction table end to end.
    """
    from .services import derived_sql as dsql

    bounds = ch.query(
        "SELECT DATE(MIN(transaction_date)) AS lo, DATE(MAX(transaction_date)) AS hi "
        "FROM `transaction`").rows[0]
    if not bounds or not bounds.get("lo"):
        raise RuntimeError(f"no transactions in {ch.target.label}")

    banks = {r["bank_code"]: r["bank_name"] for r in
             ch.query("SELECT bank_code, bank_name FROM `bank`").rows}
    accounts = [
        AccountRecord(r["account_id"], r["entity_id"], r["account_last4"], r["bank_code"],
                      banks.get(r["bank_code"], r["bank_code"]), int(r["program_id"]),
                      float(r["available_balance"]))
        for r in ch.query(
            "SELECT account_id, entity_id, "
            f"{dsql.account_last4('a')} AS account_last4, bank_code, program_id, "
            "available_balance FROM `account` AS a").rows
    ]
    hi = str(bounds["hi"])
    # The window scan is the one slow statement (~5 s per day of data over this
    # link). Its result is kept in Redis keyed by source and newest day; on a miss
    # the context starts with an empty list and a background thread fills it, so
    # startup never blocks on the remote. Until it lands, a counterparty question
    # is asked to clarify rather than guessed.
    cp_key = f"{ch.target.host}:{ch.target.port}/{ch.target.database}@{hi}/{COUNTERPARTY_WINDOW_DAYS}"
    cp_rows = app_state.cache.get_json("counterparties", cp_key) if app_state.cache else None
    counterparties = _counterparty_records(cp_rows) if cp_rows is not None else []
    entity_rows = ch.query(
        "SELECT entity_id, COUNT(*) AS n FROM `account` GROUP BY entity_id ORDER BY n DESC").rows
    entities = [r["entity_id"] for r in entity_rows]
    default_entity = os.getenv("TBX_DEFAULT_ENTITY") or (entities[0] if entities else None)
    version = f"mysql-live-{ch.target.host}-{ch.target.database}-{hi}"
    log.info("dataset %s: %s..%s, %d accounts, %d counterparties, %d entities",
             version, bounds["lo"], hi, len(accounts), len(counterparties), len(entities))
    return DatasetContext(
        calendar=DatasetCalendar(min_date=date.fromisoformat(str(bounds["lo"])),
                                 max_date=date.fromisoformat(hi)),
        counterparties=counterparties, accounts=accounts, banks=banks, entities=entities,
        currency="INR", dataset_version=version, default_entity=default_entity)


def _counterparty_records(rows: list[dict]) -> list[CounterpartyRecord]:
    return [
        CounterpartyRecord(r["counterparty"], int(r["n"]), r["channel"] or "OTHER",
                           frozenset(str(r["entities"] or "").split(",")))
        for r in rows
    ]


def _counterparty_rows(ch: MySQLClient, hi: str) -> list[dict]:
    from .services import derived_sql as dsql
    slow = MySQLClient(ch.target, timeout=max(settings.query_timeout, 300),
                       max_result_rows=MAX_COUNTERPARTIES + 1)
    return slow.query(
        f"SELECT {dsql.counterparty('t')} AS counterparty, COUNT(*) AS n, "
        f"SUBSTRING_INDEX(GROUP_CONCAT(DISTINCT {dsql.channel('t')}), ',', 1) AS channel, "
        "GROUP_CONCAT(DISTINCT a.entity_id) AS entities "
        "FROM `transaction` AS t JOIN `account` AS a ON a.account_id = t.account_id "
        "WHERE t.transaction_date >= DATE_SUB(%(hi)s, INTERVAL %(days)s DAY) "
        "GROUP BY counterparty HAVING counterparty <> '' "
        "ORDER BY n DESC LIMIT %(lim)s",
        {"hi": hi, "days": COUNTERPARTY_WINDOW_DAYS, "lim": MAX_COUNTERPARTIES}).rows


def load_counterparties_async(ctx: DatasetContext, ch: MySQLClient) -> None:
    """Fill `ctx.counterparties` from the remote in the background and cache the rows.
    Writes only into the context object it was given, so a source switched in the
    meantime is never overwritten."""
    if ctx.counterparties:
        return
    hi = ctx.calendar.max_date.isoformat()
    cp_key = f"{ch.target.host}:{ch.target.port}/{ch.target.database}@{hi}/{COUNTERPARTY_WINDOW_DAYS}"

    def _run() -> None:
        try:
            rows = _counterparty_rows(ch, hi)
        except Exception as e:  # noqa: BLE001 -- a slow remote must not kill the process
            log.warning("counterparty list unavailable: %s", e)
            return
        ctx.counterparties = _counterparty_records(rows)
        if app_state.cache:
            app_state.cache.set_json("counterparties", cp_key, value=rows, ttl=86_400)
        log.info("counterparty list ready: %d names from the last %d days",
                 len(rows), COUNTERPARTY_WINDOW_DAYS)

    threading.Thread(target=_run, name="counterparties", daemon=True).start()


def rebuild_dataset_context() -> None:
    """Re-read the dataset facts after the source changes.

    The judge is rebuilt with the new dataset version so cached plans and answers
    from the previous source can never be served against the new one.
    """
    assert app_state.ch is not None, "app state not initialised"
    app_state.ctx = build_dataset_context(app_state.ch)
    load_counterparties_async(app_state.ctx, app_state.ch)
    if app_state.cache is not None:
        app_state.judge = Judge(app_state.cache, app_state.ctx.dataset_version)
        if app_state.router is not None:
            app_state.router.judge = app_state.judge
    app_state.conversations.clear()


def env_target() -> MySQLTarget:
    """The source configured in the environment (MYSQL_*)."""
    return MySQLTarget(host=settings.mysql_host, port=settings.mysql_port,
                       database=settings.mysql_db, user=settings.mysql_user,
                       password=settings.mysql_password)


def connect_source(target: MySQLTarget) -> None:
    """Make `target` the live source: swap the client, re-read the context, and only
    then commit. A source that cannot be read leaves the previous one in place."""
    previous_client = app_state.ch
    client = MySQLClient(target, timeout=settings.query_timeout, max_result_rows=50_000)
    if not client.ping():
        raise RuntimeError(f"MySQL unreachable at {target.label}")
    app_state.ch = client
    try:
        rebuild_dataset_context()
    except Exception:
        app_state.ch = previous_client
        if previous_client is not None:
            app_state.ctx = build_dataset_context(previous_client)
        raise
    app_state.source = target
    save_active_source(target)
    log.info("data source: %s", target.label)


SOURCE_KEY = "active"
"""Cache slot holding which endpoint the assistant is answering from, so a restart
keeps the source the Data Source page selected. Only the non-secret connection
identity is stored; the password never is, so a restart can only re-open an
endpoint whose password is the configured one."""


def save_active_source(target: MySQLTarget | None) -> None:
    if not app_state.cache:
        return
    app_state.cache.set_json("source", SOURCE_KEY, ttl=None,
                             value={"target": target.public() if target else None})


def restore_active_source() -> MySQLTarget:
    """The endpoint to open at startup: the one saved by the Data Source page if its
    identity is complete and it shares the configured password, else MYSQL_*."""
    env = env_target()
    if not app_state.cache:
        return env
    doc = app_state.cache.get_json("source", SOURCE_KEY) or {}
    t = doc.get("target") or {}
    if not t or not t.get("host") or not t.get("database"):
        return env
    return MySQLTarget(host=t["host"], port=int(t.get("port") or 3306),
                       database=t["database"], user=t.get("user") or env.user,
                       password=env.password)


def clear_active_source() -> None:
    """Back to the configured endpoint."""
    save_active_source(None)


def startup() -> None:
    """Build the singletons; a non-compliant configured model stops the service here."""
    # The cache comes first: it holds which endpoint a previous run left active.
    app_state.cache = Cache(settings.redis_url)
    target = restore_active_source()
    try:
        connect_source(target)
    except Exception:
        if target == env_target():
            raise
        log.warning("saved data source %s is unreadable; using the configured endpoint",
                    target.label)
        clear_active_source()
        connect_source(env_target())

    completion_fn = None
    if os.getenv("TBX_USE_STUB_LLM") == "1":
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
        from stub_llm import stub_completion  # type: ignore
        completion_fn = stub_completion
        log.warning("TBX_USE_STUB_LLM=1 -- using the offline stub planner, NOT a real model")

    app_state.judge = Judge(app_state.cache, app_state.ctx.dataset_version)
    router = ModelRouter(completion_fn=completion_fn, timeout=settings.llm_timeout,
                         judge=app_state.judge)
    if completion_fn is None:
        from .llm.catalog import check_compliance
        for warning in check_compliance(router.configured_models()):
            log.warning(warning)
    app_state.router = router
