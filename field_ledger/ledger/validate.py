"""Command + state -> Verdict. Pure: no database, no clock (time is passed in).

Each check returns a Verdict or None ("nothing to say"). `combine` merges them:
REJECT or IGNORE stops everything; any CONFIRM makes the whole thing a CONFIRM;
WARN flags accumulate.
"""

from datetime import datetime, timedelta

from .ids import canonical_item, canonical_location, suggest
from .model import Kind, Move, Rename, Verdict, Void
from .state import State, ancestors, makes_cycle, resolve

DUPLICATE_WINDOW = timedelta(minutes=2)


def node_id(raw: str, state: State) -> str | None:
    """Raw text -> an existing node's id, or None.

    Most node ids are `PFX-NN` and get canonicalised. Some are not ID-shaped at all
    (a branch node is named after the branch, a location node after the location), so
    text that already names a node is taken as typed.
    """
    name = raw.strip()
    if name in state.items:
        return name
    item = canonical_item(raw)
    return item if item in state.items else None


def canonical_destination(raw: str, state: State) -> str:
    """A node id names a container (BAT-01 > CAS-01, feat/x > drone-3); anything else is
    a plain location. Not alias-resolved: this is what gets stored, and renames apply at
    read time."""
    return node_id(raw, state) or canonical_location(raw)


def not_found(raw: str, state: State) -> str:
    """Why `raw` names no node. A missing KIND-NN is a kit typo or an item never added;
    anything else is a build or location name, and a build only exists from its first
    deploy (and is gone again if that deploy is undone)."""
    item = canonical_item(raw)
    hint = suggest(item or raw.strip(), set(state.items))
    if item is not None:
        tail = f" Did you mean {hint}?" if hint else " Add it first with `fl add`."
        return f"{item} is not in the kit.{tail}"
    tail = f" Did you mean {hint}?" if hint else ""
    return (f"'{raw.strip()}' is not in the ledger. Items look like BAT-07; a build appears "
            f"at its first deploy.{tail}")


SEC_LABELS = ("CRIT", "HIGH", "MED", "LOW", "NA")


# --- individual checks ---------------------------------------------------------

def check_item(raw: str, state: State) -> tuple[str | None, Verdict | None]:
    """Return (canonical id, None) if the node exists, else (None, REJECT)."""
    node = node_id(raw, state)
    if node is not None:
        return node, None
    return None, Verdict(Kind.REJECT, (not_found(raw, state),))


def check_destination(dst: str, state: State) -> Verdict | None:
    """Known: fine. Close to a known one: probably a typo, ask. Otherwise: new, flag it."""
    if dst in state.locations or dst in state.items:
        return None
    hint = suggest(dst, state.locations)
    if hint:
        return Verdict(Kind.CONFIRM, (f"'{dst}' is a new location. Did you mean '{hint}'?",),
                       ("new-location",))
    return Verdict(Kind.WARN, (f"'{dst}' is a new location.",), ("new-location",))


def check_origin(item: str, src: str, state: State) -> Verdict | None:
    """Stated origin disagrees with the log: someone moved it without logging. Flag, don't
    block. Any level counts: BAT-01 in CAS-01 in the van is both 'from CAS-01' and 'from van'."""
    if not src:
        return None
    if resolve(canonical_destination(src, state), state.aliases) in ancestors(state, item):
        return None
    return Verdict(Kind.WARN, (f"Log says {item} was at "
                               f"'{state.where.get(item, 'nowhere')}', not '{src}'.",),
                   ("from-mismatch",))


def check_fixed(item: str, state: State) -> Verdict | None:
    """A location node holds things but is not moved on the fast path: ask first."""
    if item not in state.fixed:
        return None
    return Verdict(Kind.CONFIRM, (f"'{item}' is a fixed location, not kit. "
                                  "Moving it takes everything in it.",),
                   ("fixed-move",))


def check_same_place(item: str, dst: str, state: State) -> Verdict | None:
    if state.where.get(item) != dst:
        return None
    return Verdict(Kind.CONFIRM, (f"Log already has {item} at '{dst}'. "
                                  "Was it moved away and back without being logged?",),
                   ("same-place",))


def check_cycle(item: str, dst: str, state: State) -> Verdict | None:
    if not makes_cycle(state, item, dst):
        return None
    why = "that's itself" if dst == item else f"{dst} is inside {item}"
    return Verdict(Kind.REJECT, (f"{item} can't go into {dst}: {why}.",))


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
    dst = resolve(canonical_destination(cmd.dst, state), state.aliases)
    stop = check_cycle(item, dst, state) or check_duplicate(item, dst, actor, state, now)
    if stop:
        return item, stop
    return item, combine([
        check_destination(dst, state),
        check_origin(item, cmd.src, state),
        check_same_place(item, dst, state),
        check_fixed(item, state),
    ])


def validate_label(raw: str, label: str, state: State) -> tuple[str | None, str, Verdict]:
    """A security label goes on a build, and is one of a fixed five: a free-text label
    can't be counted or compared on the board. Returns (build, label, verdict)."""
    item, bad = check_item(raw, state)
    if bad:
        return None, "", bad
    if state.items[item] != "build":
        return None, "", Verdict(Kind.REJECT, (f"{item} is not a build; only builds carry a "
                                               f"security label.",))
    label = label.strip().upper()
    if label not in SEC_LABELS:
        return None, "", Verdict(Kind.REJECT, (f"'{label}' is not a security label. Use one of "
                                               f"{' / '.join(SEC_LABELS)}.",))
    return item, label, Verdict(Kind.ACCEPT)


def validate_resolve(raw: str, pick: str, state: State,
                     open_: dict[str, tuple[str, str]]) -> tuple[str | None, str, Verdict]:
    """RESOLVE settles a ⚠ by confirming one of its two candidates; anyone may."""
    item, bad = check_item(raw, state)
    if bad:
        return None, "", bad
    if item not in open_:
        return None, "", Verdict(Kind.REJECT, (f"{item} has no ⚠ to resolve.",))
    pick = resolve(canonical_destination(pick, state), state.aliases)
    if pick not in open_[item]:
        return None, "", Verdict(Kind.REJECT, (f"Pick one of {open_[item][0]} or {open_[item][1]}.",))
    return item, pick, Verdict(Kind.ACCEPT)


def validate_deploy(branch: str, dst: str, state: State) -> Verdict:
    """A deploy is a move of a branch node, except that the node may not exist yet, so
    `check_item` does not apply. Everything else about a move does."""
    if branch not in state.items:
        return check_destination(dst, state) or Verdict(Kind.ACCEPT)
    return check_cycle(branch, dst, state) or combine([
        check_destination(dst, state),
        check_same_place(branch, dst, state),
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
