"""Prompt loading. Prompts live in /prompts as versioned markdown, never as
giant string literals scattered through Python."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

def _find_prompt_dir() -> Path:
    """Locate the prompts directory.

    Explicit env var wins; otherwise walk upward from this file looking for a
    `prompts/` directory. Indexing a fixed number of parents broke as soon as
    the package was copied to a different depth inside the container.
    """
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
    # parts = [preamble, 'System', system_body, 'User', user_body]
    sections = {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}
    return sections.get("System", "").strip(), sections.get("User", "").strip()


def fill(template: str, **values: object) -> str:
    """Substitute {{key}} tokens. Unknown tokens are left untouched so the
    composer's own placeholder vocabulary survives this pass."""
    out = template
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out



# follow up and segregation of token val: pair with loop relevance

