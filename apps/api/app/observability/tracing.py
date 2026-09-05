"""Langfuse tracing; a no-op when Langfuse is not configured."""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any

log = logging.getLogger("tbx.tracing")
_client: Any = None
_checked = False


def client() -> Any | None:
    global _client, _checked
    if _checked:
        return _client
    _checked = True
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        log.info("Langfuse not configured; tracing disabled")
        return None
    try:
        from langfuse import Langfuse
        _client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST", "http://langfuse-web:3000"))
    except Exception as e:  # noqa: BLE001
        log.warning("Langfuse init failed, continuing without tracing: %s", e)
        _client = None
    return _client


@contextmanager
def trace_run(name: str, *, run_id: str, conversation_id: str, question: str):
    lf = client()
    if lf is None:
        yield None
        return
    trace = None
    try:
        trace = lf.trace(id=run_id, name=name, session_id=conversation_id,
                         input={"question": question})
        yield trace
    except Exception as e:  # noqa: BLE001
        log.warning("tracing error (ignored): %s", e)
        yield None
    finally:
        try:
            lf.flush()
        except Exception:  # noqa: BLE001
            pass
