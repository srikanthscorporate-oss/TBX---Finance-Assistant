"""SSE events streamed to the live agent timeline.

These describe *auditable actions and their outputs* -- never model reasoning.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EventType(str, Enum):
    RUN_STARTED = "run_started"
    SCOPE_CHECKED = "scope_checked"
    INTENT_DETECTED = "intent_detected"
    ENTITY_RESOLVED = "entity_resolved"
    DATES_RESOLVED = "dates_resolved"
    PLAN_VALIDATED = "plan_validated"
    CLARIFICATION_REQUIRED = "clarification_required"
    TASK_CREATED = "task_created"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    QUERY_EXECUTED = "query_executed"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_COMPLETED = "verification_completed"
    CONFIDENCE_COMPUTED = "confidence_computed"
    ANSWER_GENERATED = "answer_generated"
    FALLBACK_STARTED = "fallback_started"
    FALLBACK_COMPLETED = "fallback_completed"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"


class AgentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: EventType
    run_id: str
    seq: int
    label: str
    detail: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float | None = None
    at: datetime = Field(default_factory=datetime.utcnow)

    def to_sse(self) -> str:
        return f"event: {self.type.value}\ndata: {self.model_dump_json()}\n\n"
