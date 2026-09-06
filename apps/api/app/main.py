"""TBX Finance Assistant API."""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.v1 import admin, chat, data, models, sources
from .config.settings import settings
from .state import app_state, startup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("tbx.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start even when startup fails so /health can report the reason instead of crash-looping."""
    try:
        startup()
        log.info("startup complete (dataset %s)", app_state.ctx.dataset_version)
    except Exception as e:  # noqa: BLE001
        log.error("startup failed: %s", e)
    yield


app = FastAPI(
    title="TBX Finance Assistant",
    version="1.0.0",
    description="Conversational finance assistant. Every figure is computed "
                "deterministically and verified before it is shown.",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

if settings.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
    )

_hits: dict[str, deque] = defaultdict(deque)
"""In-process fallback limiter; Cloudflare does the real work at the edge."""


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """Redis fixed window so the limit holds across replicas; the deque is the fallback."""
    if request.url.path.startswith("/api/v1/chat"):
        client = request.headers.get("cf-connecting-ip") or (
            request.client.host if request.client else "unknown")
        count = app_state.cache.incr("ratelimit", client, str(int(time.time() // 60)), ttl=70) \
            if app_state.cache and app_state.cache.enabled else 0
        if not count:
            now = time.time()
            window = _hits[client]
            while window and now - window[0] > 60:
                window.popleft()
            window.append(now)
            count = len(window)
        if count > settings.rate_limit_per_minute:
            return JSONResponse(
                {"detail": "Too many requests. Please slow down."}, status_code=429)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.middleware("http")
async def record_usage(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    if request.url.path == "/api/v1/chat":
        response.headers["X-Duration-Ms"] = f"{(time.perf_counter() - started) * 1000:.1f}"
    return response


app.include_router(chat.router)
app.include_router(data.router)
app.include_router(admin.router)
app.include_router(models.router)
app.include_router(sources.router)


@app.get("/health")
async def health():
    """`planner` is "stub" when the offline planner is wired in; such runs measure
    the deterministic pipeline, not real NLU."""
    ready = app_state.ready
    body = {
        "status": "ok" if ready else "degraded",
        "ready": ready,
        "env": settings.env,
        "dataset_version": app_state.ctx.dataset_version if app_state.ctx else None,
        "dataset_window": (
            f"{app_state.ctx.calendar.min_date}..{app_state.ctx.calendar.max_date}"
            if app_state.ctx else None),
        "counterparties": len(app_state.ctx.counterparties) if app_state.ctx else 0,
        "accounts": len(app_state.ctx.accounts) if app_state.ctx else 0,
        "planner": "stub" if os.getenv("TBX_USE_STUB_LLM") == "1" else "model",
        "source": f"mysql:{app_state.source.database}" if app_state.source else "bundled",
    }
    return JSONResponse(body, status_code=200 if ready else 503)
