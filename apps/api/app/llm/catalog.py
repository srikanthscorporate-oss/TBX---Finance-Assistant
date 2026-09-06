"""The model catalog: every model the assistant may use.

Each entry records its parameter count so the 20B ceiling is enforced at startup
by `check_compliance`. The catalog feeds the dropdown, the router tiers and the
model-choice note. An entry whose provider key is missing is listed as
unavailable rather than hidden.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass, field

log = logging.getLogger("tbx.catalog")

PARAM_LIMIT_B = float(os.getenv("MODEL_PARAM_LIMIT_B", "20"))
"""Ceiling on total parameters, in billions."""

TOLERANCE = float(os.getenv("MODEL_PARAM_TOLERANCE", "0.05"))
"""Fraction over the limit that warns instead of refusing.

Covers the nominal 20B class (gpt-oss-20b is 20.9B total, 3.6B active) without
admitting a 24B model.
"""


@dataclass(frozen=True)
class CatalogModel:
    """One catalog entry.

    `params_b` is total parameters in billions and `active_params_b` the MoE
    active count. `list_when_keyed` marks a paid provider the user opts into by
    adding its key (Sarvam); paid OpenRouter models never ride in on the
    free-tier key. `verified` means it passed the planning probe. `size_known`
    is False when the provider publishes no parameter count.
    """
    id: str
    label: str
    provider: str
    params_b: float
    active_params_b: float | None = None
    api_key_env: str = ""
    api_base: str | None = None
    supports_json_mode: bool = True
    free: bool = True
    list_when_keyed: bool = False
    verified: bool = False
    note: str = ""
    input_cost_per_m: float = 0.0
    output_cost_per_m: float = 0.0
    size_known: bool = True
    discovered: bool = False

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
        """Within the ceiling and free, or on a provider the user opted into by adding its key."""
        return (not self.refused) and (self.free or (self.list_when_keyed and self.available))

    @property
    def size_label(self) -> str:
        if not self.size_known:
            return "size not published"
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
            "over_limit": self.over_limit, "refused": self.refused,
            "size_known": self.size_known, "discovered": self.discovered, "note": self.note,
        }


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
"""Ordered: the first available entry is the auto primary, the next available is the alternate."""

EXCLUDED = {
    "groq/openai/gpt-oss-120b": "120B, six times the ceiling",
    "openai/sarvam-m": "24B, over the ceiling",
    "openrouter/inclusionai/ling-3.0-flash-fin:free": "~100B MoE, over the ceiling",
    "openrouter/google/gemma-4-26b-a4b-it:free": "26B, over the ceiling",
    "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": "30B, over the ceiling",
    "groq/compound": "agentic system over undisclosed large models",
}
"""Refused by id, with the reason."""


_SIZE_RE = re.compile(r"(?<![a-z0-9])(\d+(?:\.\d+)?)b(?:-a(\d+(?:\.\d+)?)b)?(?![a-z0-9])", re.I)
_discovered: list[CatalogModel] | None = None
_discovered_at: float = 0.0
DISCOVERY_TTL_S = 3600


def _parse_size(model_id: str, name: str) -> tuple[float | None, float | None]:
    for text in (model_id, name):
        m = _SIZE_RE.search(text.replace("_", "-"))
        if m:
            return float(m.group(1)), (float(m.group(2)) if m.group(2) else None)
    return None, None


def discover_openrouter_free(force: bool = False) -> list[CatalogModel]:
    """Free models on the OpenRouter key, refreshed hourly.

    All are listed so the user sees the whole set; only those with a published
    size within the ceiling are selectable, and an unpublished size counts as
    over the ceiling. Discovery failure is silent; the static list still works.
    """
    global _discovered, _discovered_at
    import time
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        return []
    if _discovered is not None and not force and time.time() - _discovered_at < DISCOVERY_TTL_S:
        return _discovered
    try:
        req = urllib.request.Request("https://openrouter.ai/api/v1/models",
                                     headers={"Authorization": f"Bearer {key}"})
        data = json.loads(urllib.request.urlopen(req, timeout=10).read())
    except Exception as e:  # noqa: BLE001
        log.warning("openrouter discovery failed: %s", e)
        return _discovered or []
    static_ids = {m.id for m in CATALOG}
    out: list[CatalogModel] = []
    for m in data.get("data", []):
        pr = m.get("pricing") or {}
        try:
            free = float(pr.get("prompt") or 0) == 0 and float(pr.get("completion") or 0) == 0
        except ValueError:
            free = False
        if not free:
            continue
        mid = f"openrouter/{m['id']}"
        if mid in static_ids or mid in EXCLUDED:
            continue
        total, active = _parse_size(m["id"], m.get("name") or "")
        arch = m.get("architecture") or {}
        outputs = arch.get("output_modalities") or []
        if (outputs and "text" not in outputs) or any(
                k in m["id"] for k in ("lyria", "content-safety", "guard", "embed", "tts", "whisper")) \
                or m["id"] == "openrouter/free":
            continue
        known = total is not None
        out.append(CatalogModel(
            id=mid, label=((m.get("name") or m["id"]).split(":", 1)[-1].strip() or m["id"])[:40],
            provider="openrouter",
            params_b=total if known else PARAM_LIMIT_B * 10, active_params_b=active,
            api_key_env="OPENROUTER_API_KEY", supports_json_mode=False, free=True,
            verified=False, size_known=known, discovered=True,
            note=("published size" if known else "size not published; cannot be shown to comply")))
    _discovered, _discovered_at = out, time.time()
    log.info("openrouter discovery: %d free models, %d within the ceiling",
             len(out), sum(1 for m in out if not m.refused))
    return out


def all_models() -> list[CatalogModel]:
    return CATALOG + discover_openrouter_free()


def by_id(model_id: str) -> CatalogModel | None:
    return next((m for m in all_models() if m.id == model_id), None)


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

    Returns warnings for in-band entries; raises for anything over the band or
    absent from the catalog, whose size is therefore unknown.
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
