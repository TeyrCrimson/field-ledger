"""Text grammar -> Command. Shared by the CLI, file import, and (later) the web page.

    MOVE <ITEM> [<FROM>] > <TO>     '->' also works. FROM and TO may contain spaces.
    WHERE <ITEM>
    AT <LOCATION>
    VOID <EVENT-ID> <reason...>
    RENAME <OLD> > <NEW>            location typo fix
"""

import re

from .model import At, Command, Move, Rename, Void, Where

ARROW = re.compile(r"\s*-?>\s*")
USAGE = {
    "MOVE": "MOVE <ITEM> [<FROM>] > <TO>   e.g. MOVE BAT-07 truck > site-B",
    "WHERE": "WHERE <ITEM>",
    "AT": "AT <LOCATION>",
    "VOID": "VOID <EVENT-ID> <reason>",
    "RENAME": "RENAME <OLD LOCATION> > <NEW LOCATION>",
}


class ParseError(ValueError):
    pass


def split_arrow(text: str, keyword: str) -> tuple[str, str]:
    """'a b > c' -> ('a b', 'c'). Exactly one arrow, both sides non-empty."""
    parts = ARROW.split(text)
    if len(parts) != 2 or not all(p.strip() for p in parts):
        raise ParseError(f"expected one '>' with text on both sides. Usage: {USAGE[keyword]}")
    return parts[0].strip(), parts[1].strip()


def parse_move(rest: str) -> Move:
    left, dst = split_arrow(rest, "MOVE")
    item, _, src = left.partition(" ")
    return Move(item=item, dst=dst, src=src.strip())


def parse_single(rest: str, keyword: str) -> str:
    if not rest:
        raise ParseError(f"missing argument. Usage: {USAGE[keyword]}")
    return rest


def parse_void(rest: str) -> Void:
    ref, _, reason = rest.partition(" ")
    if not ref or not reason.strip():
        raise ParseError(f"a reason is required. Usage: {USAGE['VOID']}")
    return Void(ref=ref, reason=reason.strip())


def parse(line: str) -> Command:
    keyword, _, rest = line.strip().partition(" ")
    keyword, rest = keyword.upper(), rest.strip()
    if keyword == "MOVE":
        return parse_move(rest)
    if keyword == "WHERE":
        return Where(item=parse_single(rest, keyword))
    if keyword == "AT":
        return At(location=parse_single(rest, keyword))
    if keyword == "VOID":
        return parse_void(rest)
    if keyword == "RENAME":
        return Rename(*split_arrow(rest, "RENAME"))
    raise ParseError(f"unknown command '{keyword}'. Expected one of: {', '.join(USAGE)}")
