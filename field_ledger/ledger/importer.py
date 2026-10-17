"""Bulk import from text: notes-app dumps, WhatsApp/Telegram exports.

Only UPPERCASE commands are picked up, anywhere in a line, so a chat line like
`[17/10/26, 13:05] Teyr: MOVE BAT-07 > site-B` works but "we should move the truck"
is ignored.

Event ids are derived from the text itself (actor + line + how many times that exact
line appeared before), so importing the same export twice adds nothing new.
"""

import re
import uuid

COMMAND_RE = re.compile(r"\b(MOVE|VOID|RENAME)\s.*$")
NAMESPACE = uuid.UUID("6f1c3a52-6f63-4b39-9a51-6c65646765f1")  # fixed: changing it breaks idempotency


def extract_commands(text: str) -> list[tuple[int, str]]:
    """(line number, command text) for every line that contains a command."""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = COMMAND_RE.search(line)
        if match:
            found.append((number, match.group(0).strip()))
    return found


def import_ids(actor: str, commands: list[tuple[int, str]]) -> list[str]:
    """Deterministic id per command. Repeated identical lines get distinct ids."""
    seen: dict[str, int] = {}
    ids = []
    for _, line in commands:
        seen[line] = seen.get(line, 0) + 1
        ids.append(str(uuid.uuid5(NAMESPACE, f"{actor}|{line}|{seen[line]}")))
    return ids
