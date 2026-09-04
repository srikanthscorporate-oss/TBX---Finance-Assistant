"""Provider-agnostic model routing.

Policy (see docs/plan-review.md): the SMALLEST capable model is the default and
escalation is a measured event, not an assumption. We escalate only when the
small model demonstrably failed -- a plan that would not validate, or a composer
draft rejected twice -- never on a guess about "complexity".

Every call is recorded so the escalation rate, token count and cost per query
can be reported. That reporting is the deliverable for the model-efficiency
criterion; it is not optional instrumentation.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class Tier(str, Enum):
    SMALL = "small"          # default for planning and composition
    ESCALATION = "escalation"  # only after a measured small-model failure
    FALLBACK = "fallback"    # different provider, same size class
    SELFHOSTED = "selfhosted"  # optional; see RUNPOD_* env


@dataclass
class ModelSpec:
    tier: Tier
    model: str
    api_base: str | None = None
    api_key_env: str = "GROQ_API_KEY"
    # USD per 1M tokens; used for the cost column in the efficiency report.
    input_cost_per_m: float = 0.05
    output_cost_per_m: float = 0.08
    # Not every endpoint honours response_format. Several free OpenRouter models
    # reject it or ignore it and emit fenced JSON instead, so ask per model
    # rather than sending it everywhere and losing the call.
    supports_json_mode: bool = True


@dataclass
class LLMCall:
    tier: Tier
    model: str
    purpose: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_ms: float = 0.0
    cost_usd: float = 0.0
    ok: bool = True
    error: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class UsageLedger:
    """Per-run accounting. Aggregated into the admin metrics page."""

    calls: list[LLMCall] = field(default_factory=list)

    def record(self, call: LLMCall) -> None:
        self.calls.append(call)

    @property
    def total_tokens(self) -> int:
        return sum(c.total_tokens for c in self.calls)

    @property
    def total_cost_usd(self) -> float:
        return round(sum(c.cost_usd for c in self.calls), 6)

    @property
    def escalated(self) -> bool:
        return any(c.tier is Tier.ESCALATION for c in self.calls)

    def summary(self) -> list[dict[str, Any]]:
        return [
            {"tier": c.tier.value, "model": c.model, "purpose": c.purpose,
             "prompt_tokens": c.prompt_tokens, "completion_tokens": c.completion_tokens,
             "duration_ms": round(c.duration_ms, 1), "cost_usd": round(c.cost_usd, 6),
             "ok": c.ok}
            for c in self.calls
        ]


def default_registry() -> dict[Tier, ModelSpec]:
    return {
        Tier.SMALL: ModelSpec(
            Tier.SMALL, os.getenv("MODEL_PLANNER", "groq/openai/gpt-oss-20b"),
            api_key_env="GROQ_API_KEY", input_cost_per_m=0.10, output_cost_per_m=0.50),
        Tier.ESCALATION: ModelSpec(
            Tier.ESCALATION, os.getenv("MODEL_ESCALATION", "groq/openai/gpt-oss-120b"),
            api_key_env="GROQ_API_KEY", input_cost_per_m=0.15, output_cost_per_m=0.75),
        # Free tier by policy. Free endpoints are heavily rate limited, which is
        # precisely why this is the fallback and not the primary: it absorbs a
        # provider outage without adding cost.
        Tier.FALLBACK: ModelSpec(
            Tier.FALLBACK,
            os.getenv("MODEL_FALLBACK", "openrouter/inclusionai/ling-3.0-flash-fin:free"),
            api_key_env="OPENROUTER_API_KEY",
            input_cost_per_m=0.0, output_cost_per_m=0.0,
            supports_json_mode=False),
        Tier.SELFHOSTED: ModelSpec(
            Tier.SELFHOSTED, os.getenv("MODEL_SELFHOSTED", ""),
            api_base=os.getenv("RUNPOD_BASE_URL") or None,
            api_key_env="RUNPOD_API_KEY", input_cost_per_m=0.0, output_cost_per_m=0.0),
    }


class NoProviderConfigured(RuntimeError):
    pass


class ModelRouter:
    """Thin wrapper over LiteLLM.

    `completion_fn` is injectable so the pipeline is testable without a network
    or an API key -- the offline stub in tests/ implements the same signature.
    """

    def __init__(self, registry: dict[Tier, ModelSpec] | None = None,
                 completion_fn: Callable[..., Any] | None = None,
                 timeout: int = 20):
        self.registry = registry or default_registry()
        self.timeout = timeout
        self._completion = completion_fn

    def _resolve_completion(self):
        if self._completion is not None:
            return self._completion
        try:
            from litellm import completion  # imported lazily; heavy
        except ImportError as e:  # pragma: no cover
            raise NoProviderConfigured("litellm is not installed") from e
        self._completion = completion
        return self._completion

    def available(self, tier: Tier) -> bool:
        spec = self.registry.get(tier)
        if not spec or not spec.model:
            return False
        return bool(os.getenv(spec.api_key_env))

    def call(self, *, tier: Tier, purpose: str, system: str, user: str,
             ledger: UsageLedger, json_mode: bool = False,
             max_tokens: int = 600, temperature: float = 0.0) -> str:
        """One completion. Falls back to a different provider on transport
        failure; never silently escalates to a larger model."""
        order = [tier]
        if tier is not Tier.FALLBACK and self.available(Tier.FALLBACK):
            order.append(Tier.FALLBACK)

        last_error: Exception | None = None
        for attempt_tier in order:
            spec = self.registry[attempt_tier]
            if not spec.model:
                continue
            started = time.perf_counter()
            try:
                completion = self._resolve_completion()
                kwargs: dict[str, Any] = {
                    "model": spec.model,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "timeout": self.timeout,
                }
                if spec.api_base:
                    kwargs["api_base"] = spec.api_base
                if json_mode and spec.supports_json_mode:
                    kwargs["response_format"] = {"type": "json_object"}
                # These are extraction and templating tasks, not puzzles. Keep
                # reasoning minimal so the budget goes to the actual output.
                if "gpt-oss" in spec.model:
                    kwargs["reasoning_effort"] = "low"

                resp = completion(**kwargs)
                choice = resp["choices"][0]
                text = choice["message"]["content"]

                # Reasoning models spend budget before emitting content, so a
                # length stop is common and produces half a sentence. Treat it
                # as a failure here rather than letting a truncated draft flow
                # downstream and be judged on its content.
                if choice.get("finish_reason") == "length":
                    raise ValueError(
                        f"{spec.model} hit the {max_tokens}-token cap before finishing")
                usage = resp.get("usage", {}) or {}
                pt = int(usage.get("prompt_tokens", 0))
                ct = int(usage.get("completion_tokens", 0))
                cost = (pt / 1e6) * spec.input_cost_per_m + (ct / 1e6) * spec.output_cost_per_m
                ledger.record(LLMCall(
                    tier=attempt_tier, model=spec.model, purpose=purpose,
                    prompt_tokens=pt, completion_tokens=ct,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    cost_usd=cost, ok=True))
                return text
            except Exception as e:  # noqa: BLE001 -- provider errors are opaque
                last_error = e
                ledger.record(LLMCall(
                    tier=attempt_tier, model=spec.model, purpose=purpose,
                    duration_ms=(time.perf_counter() - started) * 1000,
                    ok=False, error=str(e)[:200]))
                continue

        raise NoProviderConfigured(
            f"all providers failed for {purpose}: {last_error}"
        ) from last_error


def extract_json(text: str) -> dict[str, Any]:
    """Pull a JSON object out of a model response.

    Small models wrap JSON in prose or fences more often than large ones; being
    tolerant here is cheaper than escalating to a bigger model for formatting.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, depth = text.find("{"), 0
    if start == -1:
        raise ValueError("no JSON object in model response")
    for i, ch in enumerate(text[start:], start):
        depth += (ch == "{") - (ch == "}")
        if depth == 0:
            return json.loads(text[start:i + 1])
    raise ValueError("unterminated JSON object in model response")
