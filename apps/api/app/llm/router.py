"""Provider-agnostic model routing.

Auto mode starts on the smallest verified catalog model. A measured failure
retries the same model with feedback, then a different compliant model; nothing
escalates to a larger one. Transport failures fall through to the other
configured providers. A pinned model is honoured exactly, with no silent switch.
Every call is recorded for the usage report.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from . import catalog
from .catalog import CatalogModel


class Tier(str, Enum):
    """PRIMARY and ALTERNATE are the auto-mode pair, FALLBACK and REGIONAL other
    providers, PINNED a dropdown choice."""
    PRIMARY = "primary"
    ALTERNATE = "alternate"
    FALLBACK = "fallback"
    REGIONAL = "regional"
    PINNED = "pinned"


@dataclass
class ModelSpec:
    tier: Tier
    model: str
    api_base: str | None = None
    api_key_env: str = "GROQ_API_KEY"
    input_cost_per_m: float = 0.0
    output_cost_per_m: float = 0.0
    supports_json_mode: bool = True
    params_b: float | None = None

    @classmethod
    def from_catalog(cls, tier: Tier, m: CatalogModel) -> "ModelSpec":
        return cls(tier=tier, model=m.id, api_base=m.api_base,
                   api_key_env=m.api_key_env, input_cost_per_m=m.input_cost_per_m,
                   output_cost_per_m=m.output_cost_per_m,
                   supports_json_mode=m.supports_json_mode, params_b=m.params_b)


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
    def switched_model(self) -> bool:
        """True when a run needed more than its first model."""
        return len({c.model for c in self.calls if c.ok}) > 1

    def summary(self) -> list[dict[str, Any]]:
        return [
            {"tier": c.tier.value, "model": c.model, "purpose": c.purpose,
             "prompt_tokens": c.prompt_tokens, "completion_tokens": c.completion_tokens,
             "duration_ms": round(c.duration_ms, 1), "cost_usd": round(c.cost_usd, 6),
             "ok": c.ok, "error": c.error}
            for c in self.calls
        ]


def _env_model(name: str) -> str:
    return (os.getenv(name) or "").strip()


def default_registry() -> dict[Tier, ModelSpec]:
    """Build the tiers from env overrides, falling back to catalog ordering.

    Every entry passes through the catalog, so an env var naming a model that is
    not catalogued (and therefore of unknown size) fails at startup.
    """
    def spec_for(tier: Tier, env_name: str, fallback: CatalogModel | None) -> ModelSpec | None:
        override = _env_model(env_name)
        entry = catalog.by_id(override) if override else fallback
        if override and entry is None:
            return ModelSpec(tier=tier, model=override, api_key_env="")
        return ModelSpec.from_catalog(tier, entry) if entry else None

    primary = catalog.auto_primary()
    alternate = catalog.auto_alternate(primary)

    registry: dict[Tier, ModelSpec] = {}
    for tier, env_name, fb in (
        (Tier.PRIMARY, "MODEL_PRIMARY", primary),
        (Tier.ALTERNATE, "MODEL_ALTERNATE", alternate),
        (Tier.FALLBACK, "MODEL_FALLBACK", None),
        (Tier.REGIONAL, "MODEL_REGIONAL", None),
    ):
        spec = spec_for(tier, env_name, fb)
        if spec:
            registry[tier] = spec
    return registry


class NoProviderConfigured(RuntimeError):
    pass


class AllModelsRateLimited(RuntimeError):
    """Every candidate model was throttled; distinct from a planning failure so the user is told."""

    def __init__(self, retry_after_s: int, models: list[str]):
        self.retry_after_s = retry_after_s
        self.models = models
        super().__init__(f"rate limited on {', '.join(models)}; retry in {retry_after_s}s")


RATE_LIMIT_RETRIES = int(os.getenv("LLM_RATE_LIMIT_RETRIES", "2"))
"""Same-model retries on a 429 before falling through; the pause honours the retry-after hint."""
RATE_LIMIT_MAX_WAIT_S = float(os.getenv("LLM_RATE_LIMIT_MAX_WAIT_S", "20"))
_RETRY_AFTER_RE = re.compile(r"try again in (?:(\d+)m)?\s*([\d.]+)s", re.I)


def _is_rate_limit(err: Exception) -> bool:
    name = type(err).__name__
    return "RateLimit" in name or "429" in str(err)


def _retry_after_seconds(err: Exception, attempt: int) -> float:
    m = _RETRY_AFTER_RE.search(str(err))
    if m:
        wait = int(m.group(1) or 0) * 60 + float(m.group(2))
    else:
        wait = 2.0 * (2 ** attempt)
    return min(wait + 0.5, RATE_LIMIT_MAX_WAIT_S)


class ModelRouter:
    """Thin wrapper over LiteLLM; `completion_fn` is injectable so tests run without a key."""

    def __init__(self, registry: dict[Tier, ModelSpec] | None = None,
                 completion_fn: Callable[..., Any] | None = None,
                 timeout: int = 20, judge: Any | None = None):
        """An injected completion function means offline mode: no keys are checked
        and the stub gets a primary and an alternate so the retry path runs."""
        self.timeout = timeout
        self._completion = completion_fn
        self.judge = judge
        self.offline = completion_fn is not None
        if registry is not None:
            self.registry = registry
        elif self.offline:
            self.registry = {
                Tier.PRIMARY: ModelSpec(Tier.PRIMARY, "stub/primary", api_key_env=""),
                Tier.ALTERNATE: ModelSpec(Tier.ALTERNATE, "stub/alternate", api_key_env=""),
            }
        else:
            self.registry = default_registry()

    def configured_models(self) -> list[str]:
        return [s.model for s in self.registry.values()]

    def available(self, tier: Tier) -> bool:
        spec = self.registry.get(tier)
        if not (spec and spec.model):
            return False
        return self.offline or bool(spec.api_key_env and os.getenv(spec.api_key_env))

    def spec_for_choice(self, choice: str | None) -> ModelSpec | None:
        """Resolve a dropdown choice. None or 'auto' means policy routing."""
        if not choice or choice == "auto":
            return None
        entry = catalog.by_id(choice)
        if entry is None or entry.refused:
            raise ValueError(f"model not permitted: {choice}")
        if not entry.available:
            raise ValueError(f"model not available (missing API key): {choice}")
        return ModelSpec.from_catalog(Tier.PINNED, entry)

    def _resolve_completion(self):
        if self._completion is not None:
            return self._completion
        try:
            from litellm import completion
        except ImportError as e:  # pragma: no cover
            raise NoProviderConfigured("litellm is not installed") from e
        self._completion = completion
        return self._completion

    def call(self, *, tier: Tier, purpose: str, system: str, user: str,
             ledger: UsageLedger, json_mode: bool = False,
             max_tokens: int = 600, temperature: float = 0.0,
             pinned: ModelSpec | None = None, prefer: str | None = None) -> str:
        """One completion.

        With `pinned`, only that model is tried. Otherwise the tier goes first,
        transport failures fall through to the other configured providers, and
        the judge's preferred model is moved to the front. Models with an open
        breaker are skipped; if none remain the call raises instead of waiting.
        """
        if pinned is not None:
            order: list[ModelSpec] = [pinned]
        else:
            order = [self.registry[tier]] if tier in self.registry else []
            for alt in (Tier.FALLBACK, Tier.REGIONAL, Tier.ALTERNATE):
                if alt is not tier and self.available(alt):
                    order.append(self.registry[alt])
            if prefer:
                order.sort(key=lambda s: 0 if s.model == prefer else 1)
            if self.judge is not None:
                closed = [s for s in order if not self.judge.is_open(s.model)]
                if not closed:
                    wait = max([self.judge.breaker_ttl(s.model) for s in order] or [30])
                    raise AllModelsRateLimited(max(1, wait), [s.model for s in order])
                order = closed
        if not order:
            raise NoProviderConfigured(f"no model configured for tier {tier.value}")

        last_error: Exception | None = None
        throttled: list[str] = []
        longest_wait = 0
        for spec in order:
            if not self.offline and not (spec.api_key_env and os.getenv(spec.api_key_env)):
                continue
            for rl_attempt in range(RATE_LIMIT_RETRIES + 1):
                started = time.perf_counter()
                try:
                    text = self._one_call(spec, purpose, system, user, ledger,
                                          json_mode, max_tokens, temperature, started)
                    return text
                except Exception as e:  # noqa: BLE001 -- provider errors are opaque
                    last_error = e
                    if _is_rate_limit(e):
                        throttled.append(spec.model)
                        m = _RETRY_AFTER_RE.search(str(e))
                        longest_wait = max(longest_wait, int((int(m.group(1) or 0) * 60 + float(m.group(2))) if m else 30))
                    if _is_rate_limit(e) and self.judge is not None:
                        m = _RETRY_AFTER_RE.search(str(e))
                        asked = (int(m.group(1) or 0) * 60 + float(m.group(2))) if m else 30.0
                        self.judge.trip(spec.model, int(min(asked, 900)) + 1)
                    if _is_rate_limit(e) and rl_attempt < RATE_LIMIT_RETRIES:
                        wait = _retry_after_seconds(e, rl_attempt)
                        ledger.record(LLMCall(
                            tier=spec.tier, model=spec.model, purpose=purpose,
                            duration_ms=(time.perf_counter() - started) * 1000,
                            ok=False, error=f"rate limited; waiting {wait:.1f}s then retrying"))
                        time.sleep(wait)
                        continue
                    ledger.record(LLMCall(
                        tier=spec.tier, model=spec.model, purpose=purpose,
                        duration_ms=(time.perf_counter() - started) * 1000,
                        ok=False, error=str(e)[:200]))
                    break

        skipped = [s.model for s in ([pinned] if pinned else list(self.registry.values()))
                   if self.judge is not None and self.judge.is_open(s.model)]
        tried = [s.model for s in order]
        if tried and all(m in throttled for m in tried):
            wait = max(longest_wait, *(self.judge.breaker_ttl(m) for m in skipped)) if skipped and self.judge else longest_wait
            raise AllModelsRateLimited(max(1, wait), sorted(set(throttled + skipped))) from last_error
        raise NoProviderConfigured(
            f"all models failed for {purpose}: {last_error}") from last_error

    def _one_call(self, spec: ModelSpec, purpose: str, system: str, user: str,
          ledger: UsageLedger, json_mode: bool, max_tokens: int,
          temperature: float, started: float) -> str:
        """gpt-oss runs at low reasoning effort; the tasks are extraction and templating."""
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
        if "gpt-oss" in spec.model:
            kwargs["reasoning_effort"] = "low"

        resp = completion(**kwargs)
        choice = resp["choices"][0]
        text = choice["message"]["content"]
        if choice.get("finish_reason") == "length":
            raise ValueError(
                f"{spec.model} hit the {max_tokens}-token cap before finishing")
        if not text or not text.strip():
            raise ValueError(f"{spec.model} returned empty content")

        usage = resp.get("usage", {}) or {}
        pt = int(usage.get("prompt_tokens", 0))
        ct = int(usage.get("completion_tokens", 0))
        cost = (pt / 1e6) * spec.input_cost_per_m + (ct / 1e6) * spec.output_cost_per_m
        ledger.record(LLMCall(
            tier=spec.tier, model=spec.model, purpose=purpose,
            prompt_tokens=pt, completion_tokens=ct,
            duration_ms=(time.perf_counter() - started) * 1000,
            cost_usd=cost, ok=True))
        return text


def extract_json(text: str) -> dict[str, Any]:
    """Pull a JSON object out of a model response, tolerating fences and prose."""
    text = (text or "").strip()
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
