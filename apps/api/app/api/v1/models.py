"""The model catalog, for the dropdown and the model-choice note."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ...llm import catalog

router = APIRouter(prefix="/api/v1", tags=["models"])


@router.get("/models")
async def models() -> dict[str, Any]:
    """Catalog for the dropdown.

    `models` is what may be selected; over-ceiling and unlisted entries are
    returned with their reason rather than hidden.
    """
    primary = catalog.auto_primary()
    alternate = catalog.auto_alternate(primary)
    return {
        "limit_b": catalog.PARAM_LIMIT_B,
        "auto": {
            "primary": primary.id if primary else None,
            "alternate": alternate.id if alternate else None,
            "policy": "Smallest verified model first. A measured failure retries the "
                      "same model with feedback, then a different compliant model. "
                      "Never a larger one.",
        },
        "models": [m.to_public() for m in catalog.all_models() if m.listed],
        "over_ceiling": [m.to_public() for m in catalog.all_models()
                         if m.free and m.refused and m.provider == "openrouter"],
        "unlisted": [{"id": m.id, "label": m.label,
                      "reason": "paid; awaiting its provider key" if m.list_when_keyed
                                else "paid model; only free models are listed"}
                     for m in catalog.all_models() if not m.refused and not m.listed],
        "excluded": [{"id": k, "reason": v} for k, v in catalog.EXCLUDED.items()],
    }
