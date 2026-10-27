"""Bulk import from text: notes-app dumps, WhatsApp/Telegram exports.

Only UPPERCASE commands are picked up, anywhere in a line, so a chat line like
`[17/10/26, 13:05] Teyr: MOVE BAT-07 > site-B` works but "we should move the truck"
is ignored.

Event ids are derived from the text itself: the whole source line, chat timestamp and
sender included, plus how many times that exact line appeared before. Not from who runs
the import, so the same export imported twice, by anyone, adds nothing new.
"""

import re
import uuid

from .ids import canonical_item, canonical_location
from .model import Move
from .parse import ParseError, parse

# ponytail: '→' is deliberately not an arrow. The ledger shares `MOV BAT-12 → van` lines to
# chat, and those are already in the ledger: re-imported, they show as rejected, never written.
COMMAND_RE = re.compile(r"\b(MOVE?|VOID|RENAME)\s.*$")       # MOV = MOVE
NAMESPACE = uuid.UUID("6f1c3a52-6f63-4b39-9a51-6c65646765f1")  # fixed: changing it breaks idempotency


def extract_commands(text: str) -> list[tuple[int, str]]:
    """(line number, command text) for every line that contains a command."""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = COMMAND_RE.search(line)
        if match:
            found.append((number, match.group(0).strip()))
    return found


def import_ids(text: str, commands: list[tuple[int, str]]) -> list[str]:
    """Deterministic id per command, from its whole source line. Repeated identical lines
    get distinct ids."""
    source = text.splitlines()
    seen: dict[str, int] = {}
    ids = []
    for number, _ in commands:
        line = source[number - 1].strip()
        seen[line] = seen.get(line, 0) + 1
        ids.append(str(uuid.uuid5(NAMESPACE, f"{line}|{seen[line]}")))
    return ids


def repeats(commands: list[tuple[int, str]]) -> dict[int, int]:
    """Line number -> the earlier line it repeats.

    A MOVE repeats when the previous MOVE of the same item in this text went to the
    same place: one move reported twice. Decided from the text alone (no clock, no
    database), so every laptop and every re-import gets the same answer.
    """
    last: dict[str, tuple[str, int]] = {}      # item -> (destination, line that said so)
    found = {}
    for number, line in commands:
        try:
            cmd = parse(line)
        except ParseError:
            continue
        if not isinstance(cmd, Move):
            continue
        item, dst = canonical_item(cmd.item) or cmd.item, canonical_location(cmd.dst)
        if item in last and last[item][0] == dst:
            found[number] = last[item][1]
        else:
            last[item] = (dst, number)
    return found
