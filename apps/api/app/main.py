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

from .api.v1 import admin, chat, data
from .config.settings import settings
from .state import app_state, startup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("tbx.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        startup()
        log.info("startup complete (dataset %s)", app_state.ctx.dataset_version)
    except Exception as e:  # noqa: BLE001
        # Start anyway so /health can report the failure rather than the
        # container crash-looping with the reason buried in logs.
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

# --- Rate limiting --------------------------------------------------------
# Simple in-process limiter. Cloudflare does the real work at the edge; this
# protects the LLM budget if something gets past it.
_hits: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path.startswith("/api/v1/chat"):
        client = request.headers.get("cf-connecting-ip") or (
            request.client.host if request.client else "unknown")
        now = time.time()
        window = _hits[client]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= settings.rate_limit_per_minute:
            return JSONResponse(
                {"detail": "Too many requests. Please slow down."}, status_code=429)
        window.append(now)

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


@app.get("/health")
async def health():
    ready = app_state.ready
    body = {
        "status": "ok" if ready else "degraded",
        "ready": ready,
        "env": settings.env,
        "dataset_version": app_state.ctx.dataset_version if app_state.ctx else None,
        "dataset_window": (
            f"{app_state.ctx.calendar.min_date}..{app_state.ctx.calendar.max_date}"
            if app_state.ctx else None),
        "vendors": len(app_state.ctx.vendors) if app_state.ctx else 0,
        # "stub" means the offline planner is wired in -- evaluation numbers
        # from such a run measure the deterministic pipeline, not real NLU.
        "planner": "stub" if os.getenv("TBX_USE_STUB_LLM") == "1" else "model",
    }
    return JSONResponse(body, status_code=200 if ready else 503)
