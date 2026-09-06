"""Loads versioned prompt markdown from /prompts."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

def _find_prompt_dir() -> Path:
    """TBX_PROMPT_DIR wins; otherwise walk up from this file, since the package depth varies."""
    env = os.getenv("TBX_PROMPT_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "prompts"
        if candidate.is_dir():
            return candidate
    raise RuntimeError(
        "prompts directory not found; set TBX_PROMPT_DIR to its location")


PROMPT_DIR = _find_prompt_dir()

_SECTION_RE = re.compile(r"^##\s+(System|User)\s*$", re.M)


@lru_cache(maxsize=32)
def load(name: str) -> tuple[str, str]:
    """Return (system, user) templates for a prompt version."""
    path = PROMPT_DIR / f"{name}.md"
    text = path.read_text()
    parts = _SECTION_RE.split(text)
    sections = {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    return sections.get("System", "").strip(), sections.get("User", "").strip()


def fill(template: str, **values: object) -> str:
    """Substitute {{key}} tokens; unknown tokens stay so composer placeholders survive."""
    out = template
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out

