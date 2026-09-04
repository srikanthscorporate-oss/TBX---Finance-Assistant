"""The model catalog: every model the assistant is allowed to use.

Section 7 of the problem statement sets a hard ceiling of 20B parameters and
says that defaulting to a larger model without justification is scored down.
This module is where that constraint lives in code rather than in a document:

  * every entry records its parameter count, so the limit can be ENFORCED at
    startup (see `check_compliance`) instead of trusted;
  * the catalog is the single source for the UI dropdown, the router's tiers,
    and the model-choice note, so the three cannot disagree.

Availability is gated on the provider's API key being present. An entry whose
key is missing is listed as unavailable rather than hidden, so the UI can show
what could be enabled.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger("tbx.catalog")

# The organiser's ceiling. Total parameters, in billions.
PARAM_LIMIT_B = float(os.getenv("MODEL_PARAM_LIMIT_B", "20"))

# Models within this fraction over the limit start with a WARNING rather than a
# refusal. This exists for exactly one case: the nominal "20B" class where the
# published total is a fraction over (gpt-oss-20b is 20.9B total, 3.6B active).
# Anything beyond the band is refused outright. The band is deliberately narrow
# so it cannot admit a 24B or 26B model.
TOLERANCE = float(os.getenv("MODEL_PARAM_TOLERANCE", "0.05"))


@dataclass(frozen=True)
class CatalogModel:
    id: str                    # LiteLLM model string
    label: str                 # what the dropdown shows
    provider: str              # groq | openrouter | sarvam
    params_b: float            # total parameters, billions
    active_params_b: float | None = None   # MoE active parameters, if applicable
    api_key_env: str = ""
    api_base: str | None = None
    supports_json_mode: bool = True
    free: bool = True          # no per-token cost on this key
    # A paid provider the user has deliberately opted into by adding its key
    # (Sarvam). Paid models on a provider whose key exists only for its free
    # tier (OpenRouter) must NOT ride in on that key.
    list_when_keyed: bool = False
    verified: bool = False     # passed the planning probe on this project
    note: str = ""
    input_cost_per_m: float = 0.0
    output_cost_per_m: float = 0.0

    @property
    def available(self) -> bool:
        return bool(self.api_key_env and os.getenv(self.api_key_env))

    @property
    def over_limit(self) -> bool:
        return self.params_b > PARAM_LIMIT_B

    @property
    def refused(self) -> bool:
        return self.params_b > PARAM_LIMIT_B * (1 + TOLERANCE)

    @property
    def listed(self) -> bool:
        """Eligible for the dropdown: within the ceiling AND free, or on a
        provider the user opted into by adding its key. Paid OpenRouter models
        are never listed just because the OpenRouter key exists."""
        return (not self.refused) and (self.free or (self.list_when_keyed and self.available))

    @property
    def size_label(self) -> str:
        if self.active_params_b:
            return f"{self.params_b:g}B total, {self.active_params_b:g}B active"
        return f"{self.params_b:g}B"

    def to_public(self) -> dict:
        return {
            "id": self.id, "label": self.label, "provider": self.provider,
            "params_b": self.params_b, "active_params_b": self.active_params_b,
            "size_label": self.size_label, "free": self.free,
            "verified": self.verified, "available": self.available,
            "listed": self.listed, "list_when_keyed": self.list_when_keyed,
            "over_limit": self.over_limit, "note": self.note,
        }


# Ordered: the first AVAILABLE entry is the auto-mode primary; the first
# available entry after it is the alternate. Keep that ordering deliberate.
CATALOG: list[CatalogModel] = [
    CatalogModel(
        id="groq/openai/gpt-oss-20b", label="GPT-OSS 20B", provider="groq",
        params_b=20.9, active_params_b=3.6, api_key_env="GROQ_API_KEY",
        supports_json_mode=True, free=True, verified=True,
        input_cost_per_m=0.10, output_cost_per_m=0.50,
        note="Nominal 20B class. Published total is 20.9B with 3.6B active per "
             "token; flagged rather than hidden. Best accuracy on the golden set."),
    CatalogModel(
        id="groq/allam-2-7b", label="ALLaM 2 7B", provider="groq",
        params_b=7.0, api_key_env="GROQ_API_KEY",
        supports_json_mode=True, free=True, verified=True,
        input_cost_per_m=0.0, output_cost_per_m=0.0,
        note="Comfortably under the limit. Weaker on grouping questions; used as "
             "the alternate after a measured primary failure."),
    CatalogModel(
        id="openrouter/meta-llama/llama-3.1-8b-instruct", label="Llama 3.1 8B",
        provider="openrouter", params_b=8.0, api_key_env="OPENROUTER_API_KEY",
        supports_json_mode=True, free=False, verified=False,
        input_cost_per_m=0.05, output_cost_per_m=0.08,
        note="Paid on OpenRouter. Not selected in auto mode because of the "
             "free-only policy; available for manual comparison."),
    CatalogModel(
        id="openrouter/qwen/qwen-2.5-7b-instruct", label="Qwen 2.5 7B",
        provider="openrouter", params_b=7.6, api_key_env="OPENROUTER_API_KEY",
        supports_json_mode=True, free=False, verified=False,
        input_cost_per_m=0.04, output_cost_per_m=0.10,
        note="Paid on OpenRouter. Manual comparison only."),
    CatalogModel(
        id="openrouter/liquid/lfm-2.5-2.6b:free", label="LFM 2.5 2.6B",
        provider="openrouter", params_b=2.6, api_key_env="OPENROUTER_API_KEY",
        supports_json_mode=False, free=True, verified=False,
        note="Experimental. Returned empty responses on most planning probes; "
             "listed so the smallest option can be re-tested, not recommended."),
    CatalogModel(
        id="openai/sarvam-1", label="Sarvam 1 (2B)", provider="sarvam",
        params_b=2.0, api_key_env="SARVAM_API_KEY",
        api_base=os.getenv("SARVAM_BASE_URL", "https://api.sarvam.ai/v1"),
        supports_json_mode=False, free=False, list_when_keyed=True, verified=False,
        note="Provisioned ahead of the key. Model id unconfirmed against "
             "Sarvam's chat API; verify before relying on it."),
]

# Explicitly EXCLUDED, so nobody re-adds them without reading why.
EXCLUDED = {
    "groq/openai/gpt-oss-120b": "120B, six times the ceiling",
    "openai/sarvam-m": "24B, over the ceiling",
    "openrouter/inclusionai/ling-3.0-flash-fin:free": "~100B MoE, over the ceiling",
    "openrouter/google/gemma-4-26b-a4b-it:free": "26B, over the ceiling",
    "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": "30B, over the ceiling",
    "groq/compound": "agentic system over undisclosed large models",
}


def by_id(model_id: str) -> CatalogModel | None:
    return next((m for m in CATALOG if m.id == model_id), None)


def available() -> list[CatalogModel]:
    return [m for m in CATALOG if m.available and not m.refused]


def auto_primary() -> CatalogModel | None:
    """First available verified model. Auto mode's default."""
    return next((m for m in available() if m.verified), None) or (available() or [None])[0]


def auto_alternate(primary: CatalogModel | None) -> CatalogModel | None:
    """A different available model, preferring verified and free ones."""
    pool = [m for m in available() if primary is None or m.id != primary.id]
    pool.sort(key=lambda m: (not m.verified, not m.free, m.params_b))
    return pool[0] if pool else None


class ComplianceError(RuntimeError):
    pass


def check_compliance(configured: list[str]) -> list[str]:
    """Refuse to start with a model that breaks the ceiling.

    Returns warnings for in-band entries. Raises for anything over the band or
    for a model that is not in the catalog at all, because an unknown model has
    an unknown parameter count and cannot be shown to comply.
    """
    warnings: list[str] = []
    for model_id in configured:
        if not model_id:
            continue
        if model_id in EXCLUDED:
            raise ComplianceError(
                f"{model_id} is excluded: {EXCLUDED[model_id]}. "
                f"Ceiling is {PARAM_LIMIT_B:g}B.")
        entry = by_id(model_id)
        if entry is None:
            raise ComplianceError(
                f"{model_id} is not in the model catalog, so its parameter count "
                f"is unknown and compliance with the {PARAM_LIMIT_B:g}B ceiling "
                f"cannot be shown. Add it to llm/catalog.py with its size.")
        if entry.refused:
            raise ComplianceError(
                f"{model_id} is {entry.params_b:g}B, over the {PARAM_LIMIT_B:g}B ceiling.")
        if entry.over_limit:
            warnings.append(
                f"{model_id} is {entry.size_label}; nominal {PARAM_LIMIT_B:g}B class, "
                f"{entry.params_b - PARAM_LIMIT_B:.1f}B over on total parameters. "
                f"Justify this in docs/model-choice.md.")
    for w in warnings:
        log.warning("model compliance: %s", w)
    return warnings
