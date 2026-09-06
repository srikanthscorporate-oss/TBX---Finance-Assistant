"""The response envelope returned to the client."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from .enums import ResponseState
from .evidence import EvidencePackage
from .plan import FinanceQueryPlan


class ClarificationOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    value: str
    hint: str | None = None


class Clarification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    options: list[ClarificationOption] = Field(default_factory=list)
    field: str | None = None


class AssistantResponse(BaseModel):
    """`answer`, `evidence`, `plan` and `chart_hint` are set only for ANSWER; `clarification`
    for CLARIFICATION_REQUIRED; `message` for DATA_UNAVAILABLE, OUT_OF_SCOPE and ERROR."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    conversation_id: str
    state: ResponseState

    answer: str | None = None
    evidence: EvidencePackage | None = None
    plan: FinanceQueryPlan | None = None
    chart_hint: str | None = None

    clarification: Clarification | None = None

    message: str | None = None
    supported_capabilities: list[str] = Field(default_factory=list)

    follow_up_suggestions: list[str] = Field(default_factory=list)
    duration_ms: float | None = None
    model_usage: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_serializer("plan")
    def _mask_entity(self, plan: FinanceQueryPlan | None, _info) -> dict[str, Any] | None:
        """The plan is echoed for tracing, so its entity id is masked on the way out.

        Conversation state stores the plan itself, not this envelope, so the compiler still
        sees the real id.
        """
        if plan is None:
            return None
        from ..services import entity_token

        data = plan.model_dump(mode="json")
        if data.get("entity_id"):
            data["entity_id"] = entity_token.mask(str(data["entity_id"]))
        return data
