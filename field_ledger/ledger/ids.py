"""Canonical forms for item IDs and locations.

Item IDs are `PFX-NN`: a 3-letter group prefix and a number, e.g. BAT-07.
Canonicalisation only applies fixed rules (case, separator, zero padding), so each
input maps to at most one ID. Anything fuzzier is a *suggestion*, never a correction.
"""

import re
from difflib import get_close_matches

ITEM_RE = re.compile(r"^([A-Za-z]{3})[\s_-]*0*(\d{1,4})$")
PREFIX_RE = re.compile(r"^[A-Za-z]{3}$")


def format_item(prefix: str, number: int) -> str:
    return f"{prefix.upper()}-{number:02d}"


def canonical_item(raw: str) -> str | None:
    """'bat7', 'BAT07', 'bat-07', 'BAT 7' -> 'BAT-07'. None if it isn't ID-shaped."""
    match = ITEM_RE.match(raw.strip())
    if not match:
        return None
    return format_item(match.group(1), int(match.group(2)))


def is_prefix(raw: str) -> bool:
    return bool(PREFIX_RE.match(raw.strip()))


def expand_group(prefix: str, start: int, count: int) -> list[str]:
    """expand_group('BAT', 1, 3) -> ['BAT-01', 'BAT-02', 'BAT-03']"""
    return [format_item(prefix, n) for n in range(start, start + count)]


def canonical_location(raw: str) -> str:
    """Lowercase, single spaces. 'Site-B ' -> 'site-b', "Yoeng's  Bag" -> "yoeng's bag"."""
    return " ".join(raw.split()).lower()


def suggest(raw: str, known: set[str], cutoff: float = 0.75) -> str | None:
    """Closest known value, or None. Used for 'did you mean' only."""
    hits = get_close_matches(raw, sorted(known), n=1, cutoff=cutoff)
    return hits[0] if hits else None
