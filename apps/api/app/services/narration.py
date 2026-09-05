"""Parse a bank statement narration into (counterparty, channel).

Indian bank exports encode the counterparty differently per rail. The formats below
are the ones in the organiser's sample rows plus the common variants; anything else
falls back to the longest alphabetic segment. Runs in the loader, so the result is a
stored LowCardinality column and never recomputed at query time. No app imports here:
the loader runs this in a bare Python container.
"""
from __future__ import annotations

import re

CHANNELS = ("NEFT", "IMPS", "UPI", "FT", "RTGS", "CHEQUE", "CHARGES", "INTEREST", "OTHER")

_IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_NUMERIC = re.compile(r"^[\d\s/-]+$")
_MASKED = re.compile(r"^X{2,}\d+$", re.I)
_MULTI_SPACE = re.compile(r"\s{2,}")
_SUFFIX = re.compile(r"\s*(?:INWD\d*|OUTWD\d*|DPF\d+|BPES\s*DPF\d+)\s*$", re.I)


def _clean(s: str) -> str:
    s = _SUFFIX.sub("", s.strip())
    s = re.sub(r"\s+", " ", s)
    return s.strip(" -/").upper()


def _is_name(seg: str) -> bool:
    seg = seg.strip()
    if len(seg) < 3 or _NUMERIC.match(seg) or _IFSC.match(seg) or _MASKED.match(seg):
        return False
    letters = sum(c.isalpha() for c in seg)
    return letters >= 3 and letters >= len(seg) * 0.6


def _longest_name(segments: list[str]) -> str:
    names = [s for s in segments if _is_name(s)]
    return _clean(max(names, key=len)) if names else ""


def parse_narration(desc: str) -> tuple[str, str]:
    d = desc.strip()
    if not d:
        return "", "OTHER"
    u = d.upper()

    if "CHARGE" in u or " FEE" in u or u.startswith("GST"):
        return _clean(d), "CHARGES"

    if u.startswith("UPI"):
        parts = [p for p in re.split(r"[-/]", d) if p.strip()]
        name = parts[1] if len(parts) > 1 and _is_name(parts[1]) else _longest_name(parts[1:])
        return _clean(name), "UPI"

    if u.startswith("IMPS"):
        parts = [p.strip() for p in d.split("/") if p.strip()]
        upper = [p.upper() for p in parts]
        after = parts[upper.index("INET") + 1:] if "INET" in upper else parts[1:]
        name = next((p for p in after if _is_name(p)), "") or _longest_name(parts[1:])
        return _clean(name), "IMPS"

    if u.startswith("NEFT") or u.startswith("RTGS"):
        rail = "NEFT" if u.startswith("NEFT") else "RTGS"
        sep = "/" if "/" in d and " - " not in d else " - "
        parts = [p for p in d.split(sep) if p.strip()]
        name = parts[-1] if len(parts) > 1 and _is_name(parts[-1]) else _longest_name(parts[1:])
        return _clean(_MULTI_SPACE.split(name)[0]), rail

    if u.startswith("FT"):
        parts = [p for p in d.split(" - ") if p.strip()]
        tail: str = parts[-1] if len(parts) > 1 else ""
        if not _is_name(tail) and "-" in d:
            tail = d.split("-")[-1]
        name = _MULTI_SPACE.split(tail.strip())[0]
        return _clean(name), "FT"

    if u.startswith("R/") or "//" in d:
        after_sep: str = d.split("//", 1)[1] if "//" in d else d
        parts = [p for p in after_sep.split("/") if p.strip()]
        return _clean(_longest_name(parts)), "OTHER"

    if "CHEQUE" in u or "CHQ" in u:
        return "CHEQUE DEPOSIT", "CHEQUE"
    if "INTEREST" in u:
        return "INTEREST", "INTEREST"

    parts = [p for p in re.split(r"[/|-]", d) if p.strip()]
    return _clean(_longest_name(parts) or d[:60]), "OTHER"
