"""Command + state -> Verdict. Pure: no database, no clock (time is passed in).

Each check returns a Verdict or None ("nothing to say"). `combine` merges them:
REJECT or IGNORE stops everything; any CONFIRM makes the whole thing a CONFIRM;
WARN flags accumulate.
"""

from datetime import datetime, timedelta

from .ids import canonical_item, canonical_location, suggest
from .model import Kind, Move, Rename, Verdict, Void
from .state import State, resolve

DUPLICATE_WINDOW = timedelta(minutes=2)


# --- individual checks ---------------------------------------------------------

def check_item(raw: str, state: State) -> tuple[str | None, Verdict | None]:
    """Return (canonical id, None) if the item exists, else (None, REJECT)."""
    item = canonical_item(raw)
    if item is None:
        return None, Verdict(Kind.REJECT, (f"'{raw}' is not an item ID (expected e.g. BAT-07)",))
    if item not in state.items:
        hint = suggest(item, set(state.items))
        tail = f" Did you mean {hint}?" if hint else " Add it first with `fl add`."
        return None, Verdict(Kind.REJECT, (f"{item} is not in the kit.{tail}",))
    return item, None


def check_destination(dst: str, state: State) -> Verdict | None:
    """Known: fine. Close to a known one: probably a typo, ask. Otherwise: new, flag it."""
    if dst in state.locations:
        return None
    hint = suggest(dst, state.locations)
    if hint:
        return Verdict(Kind.CONFIRM, (f"'{dst}' is a new location. Did you mean '{hint}'?",),
                       ("new-location",))
    return Verdict(Kind.WARN, (f"'{dst}' is a new location.",), ("new-location",))


def check_origin(item: str, src: str, state: State) -> Verdict | None:
    """Stated origin disagrees with the log: someone moved it without logging. Flag, don't block."""
    if not src or resolve(src, state.aliases) == state.where[item]:
        return None
    return Verdict(Kind.WARN, (f"Log says {item} was at '{state.where[item]}', not '{src}'.",),
                   ("from-mismatch",))


def check_same_place(item: str, dst: str, state: State) -> Verdict | None:
    if state.where[item] != dst:
        return None
    return Verdict(Kind.CONFIRM, (f"Log already has {item} at '{dst}'. "
                                  "Was it moved away and back without being logged?",),
                   ("same-place",))


def check_duplicate(item: str, dst: str, actor: str, state: State,
                    now: datetime) -> Verdict | None:
    """Same person, same item, same destination, within the window: a double tap."""
    last = state.last_event.get(item)
    if (last and last.kind == "MOVE" and last.actor == actor
            and resolve(last.dst, state.aliases) == dst and now - last.ts <= DUPLICATE_WINDOW):
        return Verdict(Kind.IGNORE, (f"Already logged {item} -> '{dst}' at {last.ts:%H:%M}.",))
    return None


# --- combining -----------------------------------------------------------------

def combine(verdicts: list[Verdict | None]) -> Verdict:
    present = [v for v in verdicts if v is not None]
    for v in present:
        if v.kind in (Kind.REJECT, Kind.IGNORE):
            return v
    messages = tuple(m for v in present for m in v.messages)
    flags = tuple(f for v in present for f in v.flags)
    if any(v.kind == Kind.CONFIRM for v in present):
        return Verdict(Kind.CONFIRM, messages, flags)
    return Verdict(Kind.WARN if flags else Kind.ACCEPT, messages, flags)


# --- per-command entry points --------------------------------------------------

def validate_move(cmd: Move, actor: str, state: State, now: datetime) -> tuple[str | None, Verdict]:
    """Returns (canonical item, verdict). The item is None when rejected."""
    item, bad = check_item(cmd.item, state)
    if bad:
        return None, bad
    dst = resolve(canonical_location(cmd.dst), state.aliases)
    src = canonical_location(cmd.src)
    duplicate = check_duplicate(item, dst, actor, state, now)
    if duplicate:
        return item, duplicate
    return item, combine([
        check_destination(dst, state),
        check_origin(item, src, state),
        check_same_place(item, dst, state),
    ])


def find_event(ref: str, state: State) -> list[str]:
    """Event ids starting with `ref`, among all events ever written (live or voided)."""
    return [e.id for e in state.events if e.id.startswith(ref)]


def validate_void(cmd: Void, state: State) -> tuple[str | None, Verdict]:
    """Resolve a (prefix of an) event id. Only live, non-VOID events can be voided."""
    hits = find_event(cmd.ref, state)
    if not hits and any(v.startswith(cmd.ref) for v in state.voided):
        return None, Verdict(Kind.REJECT, (f"Event {cmd.ref} is already void.",))
    if len(hits) != 1:
        problem = "No event" if not hits else f"{len(hits)} events"
        return None, Verdict(Kind.REJECT, (f"{problem} match '{cmd.ref}'. Use a longer id.",))
    target = next(e for e in state.events if e.id == hits[0])
    if target.kind == "VOID":
        return None, Verdict(Kind.REJECT, ("A VOID cannot itself be voided.",))
    return hits[0], Verdict(Kind.ACCEPT)


def validate_rename(cmd: Rename, state: State) -> tuple[tuple[str, str] | None, Verdict]:
    old, new = canonical_location(cmd.old), canonical_location(cmd.new)
    if old not in state.locations:
        hint = suggest(old, state.locations)
        tail = f" Did you mean '{hint}'?" if hint else ""
        return None, Verdict(Kind.REJECT, (f"'{old}' is not a known location.{tail}",))
    if old == new:
        return None, Verdict(Kind.REJECT, ("Old and new names are the same.",))
    if resolve(new, state.aliases) == old:   # new already points back at old
        return None, Verdict(Kind.REJECT, (f"Renaming '{old}' to '{new}' would create a loop.",))
    return (old, new), Verdict(Kind.ACCEPT)
