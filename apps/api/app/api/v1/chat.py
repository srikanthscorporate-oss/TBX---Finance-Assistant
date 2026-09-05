"""Chat endpoints: synchronous answer and the SSE stream behind the live agent timeline."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ...contracts.events import AgentEvent, EventType
from ...contracts.response import AssistantResponse
from ...state import app_state

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatRequest(BaseModel):
    """One turn.

    `resolved_vendor_id` answers a clarification by option id, in which case
    `message` may be empty. `model` is "auto" or a catalog model id.
    """
    message: str = Field(default="", max_length=2000)
    conversation_id: str | None = None
    resolved_vendor_id: str | None = None
    model: str | None = "auto"


@router.post("/chat", response_model=AssistantResponse)
async def chat(req: ChatRequest) -> AssistantResponse:
    """Answer one turn; a clarification reply completes the parked plan without re-planning."""
    if not app_state.ready:
        raise HTTPException(503, "dataset not loaded")

    conversation_id = req.conversation_id or uuid.uuid4().hex
    state = app_state.conversation(conversation_id)

    pipeline = app_state.pipeline()
    started = time.perf_counter()
    if req.resolved_vendor_id:
        result = await asyncio.to_thread(pipeline.run_resolved, req.resolved_vendor_id,
                                         state, req.model)
    else:
        result = await asyncio.to_thread(pipeline.run, req.message, state, req.model)
    result.duration_ms = round((time.perf_counter() - started) * 1000, 1)
    app_state.record_run(result)
    app_state.save_conversation(state)
    return result


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest, request: Request) -> StreamingResponse:
    """Run the pipeline while streaming each step to the client.

    Events carry actions and their outputs, not model reasoning. The
    X-Accel-Buffering header keeps nginx from buffering the stream.
    """
    if not app_state.ready:
        raise HTTPException(503, "dataset not loaded")

    conversation_id = req.conversation_id or uuid.uuid4().hex
    state = app_state.conversation(conversation_id)
    queue: asyncio.Queue[Any] = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def on_event(ev: AgentEvent) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, ev)

    async def run() -> None:
        pipeline = app_state.pipeline(on_event=on_event)
        try:
            started = time.perf_counter()
            if req.resolved_vendor_id:
                result = await asyncio.to_thread(pipeline.run_resolved,
                                                 req.resolved_vendor_id, state, req.model)
            else:
                result = await asyncio.to_thread(pipeline.run, req.message, state, req.model)
            result.duration_ms = round((time.perf_counter() - started) * 1000, 1)
            app_state.record_run(result)
            app_state.save_conversation(state)
            await queue.put(("result", result))
        except Exception as e:  # noqa: BLE001
            await queue.put(("error", str(e)))
        finally:
            await queue.put(None)

    async def stream():
        task = asyncio.create_task(run())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, AgentEvent):
                    yield item.to_sse()
                elif item[0] == "result":
                    payload = item[1].model_dump(mode="json")
                    yield f"event: final\ndata: {json.dumps(payload)}\n\n"
                else:
                    yield (f"event: {EventType.RUN_FAILED.value}\n"
                           f"data: {json.dumps({'error': item[1]})}\n\n")
                if await request.is_disconnected():
                    break
        finally:
            task.cancel()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str) -> dict[str, Any]:
    state = app_state.conversations.get(conversation_id)
    if state is None:
        raise HTTPException(404, "conversation not found")
    return {
        "conversation_id": conversation_id,
        "turns": state.turns,
        "last_plan": state.last_plan.model_dump(mode="json", exclude_none=True)
        if state.last_plan else None,
        "last_period": state.last_period_label,
    }
