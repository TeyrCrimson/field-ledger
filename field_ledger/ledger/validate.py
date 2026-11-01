"""Command + state -> Verdict. Pure: no database, no clock (time is passed in).

Each check returns a Verdict or None ("nothing to say"). `combine` merges them:
REJECT or IGNORE stops everything; any CONFIRM makes the whole thing a CONFIRM;
WARN flags accumulate.
"""

from datetime import datetime, timedelta

from .ids import canonical_item, canonical_location, suggest
from .model import Kind, Move, Rename, Verdict, Void
from .state import LOST, State, ancestors, makes_cycle, resolve

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


def holds_things(node: str, state: State) -> bool:
    """A place always can; an item only if its kind is a container kind; a build never."""
    if node not in state.items or node in state.fixed:
        return True
    item = canonical_item(node)
    return item is not None and item.split("-")[0] in state.containers


# --- individual checks ---------------------------------------------------------

def check_owner(state: State) -> Verdict | None:
    """Nothing moves until the ledger has a field-ops owner (Teyr, 2026-10-30): someone has
    to be there to settle the ⚠s that moves can raise. `fl init` makes its creator the owner,
    so this only stops a ledger made before owners existed, once."""
    if state.owner is not None:
        return None
    return Verdict(Kind.REJECT, ("This ledger has no field-ops owner yet, so nothing can be "
                                 "moved. `fl owner <name>` (or Owner on the board) sets one.",))


def check_item(raw: str, state: State) -> tuple[str | None, Verdict | None]:
    """Return (canonical id, None) if the node exists, else (None, REJECT)."""
    node = node_id(raw, state)
    if node is not None:
        return node, None
    return None, Verdict(Kind.REJECT, (not_found(raw, state),))


def check_id_destination(raw: str, state: State) -> Verdict | None:
    """An ID-shaped destination (`DRN-03`) that names no item. With a DRN kit in the ledger
    it's a typo: refused. With no DRN kit it may be a real place (a building number, a bay),
    so ask once; after that it's a known place. `DRN-03` used to become a location 'drn-03'
    with only a flag. A place the ledger already knows by that name is fine."""
    item = canonical_item(raw)
    if item is None or node_id(raw, state) is not None:
        return None
    place = canonical_location(raw)
    if resolve(place, state.aliases) in state.locations:
        return None
    prefix = item.split("-")[0]
    if any(i.startswith(f"{prefix}-") for i in state.items):
        return Verdict(Kind.REJECT, (not_found(raw, state),))
    return Verdict(Kind.CONFIRM, (f"'{place}' looks like an item ID, but there is no {prefix} "
                                  f"kit. A new place?",), ("id-shaped",))


def check_container(dst: str, state: State) -> Verdict | None:
    """Packing BAT-01 into BAT-02 is a slip, not a move: only container kinds hold things."""
    if holds_things(dst, state):
        return None
    item = canonical_item(dst)
    fix = (f" `fl kind {item.split('-')[0]} container yes` makes its kind one."
           if item else "")
    return Verdict(Kind.REJECT, (f"{dst} can't hold things.{fix}",))


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
        # How long ago, not a clock time: events keep the zone they were stamped in (a phone's
        # is UTC), and this module can't know the reader's. 23:59 showed as 15:59 (2026-11-01).
        minutes = max(0, int((now - last.ts).total_seconds() // 60))
        ago = "just now" if minutes == 0 else f"{minutes} min ago"
        return Verdict(Kind.IGNORE, (f"Already logged {item} -> '{dst}' {ago}.",))
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
    if no_owner := check_owner(state):
        return None, no_owner
    shape = check_id_destination(cmd.dst, state)
    if shape and shape.kind == Kind.REJECT:
        return item, shape
    dst = resolve(canonical_destination(cmd.dst, state), state.aliases)
    stop = (check_container(dst, state) or check_cycle(item, dst, state)
            or check_duplicate(item, dst, actor, state, now))
    if stop:
        return item, stop
    return item, combine([
        shape,
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


def validate_state(raw: str, value: str, state: State) -> tuple[str | None, str, Verdict]:
    """A state is one of its kind's own list (a battery: ready / depleted / ...), so the
    board can offer them as buttons and an audit can count them. Places and builds have
    none: a build's condition is its security label. Returns (item, state, verdict)."""
    item, bad = check_item(raw, state)
    if bad:
        return None, "", bad
    if item in state.fixed or state.items[item] == "build":
        what = "a place" if item in state.fixed else "a build; it carries a security label"
        return None, "", Verdict(Kind.REJECT, (f"{item} is {what}, not kit with a state.",))
    kind = (canonical_item(item) or "").split("-")[0]
    states = state.kind_states.get(kind, [])
    if not states:
        return None, "", Verdict(Kind.REJECT, (
            f"{kind or item} has no states yet. `fl kind {kind or 'XXX'} states ready depleted` "
            f"sets them.",))
    value = value.strip().lower()
    if value not in states:
        return None, "", Verdict(Kind.REJECT, (f"'{value}' is not a {kind} state. Use one of "
                                               f"{' / '.join(states)}.",))
    return item, value, Verdict(Kind.ACCEPT)


def validate_audit(raw: str, found: str, state: State) -> tuple[str | None, str, Verdict]:
    """An audit check: the item is where the log has it (`found` empty), somewhere else, or
    missing (found in Lost). Anywhere but the logged place is a mismatch, written all the
    same: the audit says what's true. Returns (item, where it was found, verdict)."""
    item, bad = check_item(raw, state)
    if bad:
        return None, "", bad
    if item in state.fixed or state.items[item] == "build":
        what = "a place" if item in state.fixed else "a build; its config is checked by CFG"
        return None, "", Verdict(Kind.REJECT, (f"{item} is {what}, not kit to audit.",))
    here = state.where.get(item, "")
    if not found.strip():
        return item, here, Verdict(Kind.ACCEPT)
    shape = check_id_destination(found, state)
    if shape and shape.kind == Kind.REJECT:
        return None, "", shape
    dst = resolve(canonical_destination(found, state), state.aliases)
    stop = check_owner(state) or check_container(dst, state) or check_cycle(item, dst, state)
    if stop:
        return None, "", stop
    if dst == here:
        return item, dst, Verdict(Kind.ACCEPT)
    seen = "missing" if dst == LOST else f"found in {dst}"
    mismatch = Verdict(Kind.WARN, (f"{item} was logged in {here or 'nowhere'}, {seen}: a mismatch.",),
                       ("mismatch",))
    return item, dst, combine([shape, mismatch, check_destination(dst, state)])


def validate_config(raw: str, digest: str, state: State, check: bool) -> tuple[str | None, Verdict]:
    """A config goes on a build. Recording the hash it already has is a repeat. A check (the
    audit, against a copy of what's deployed) is a mismatch when the hash differs, written
    all the same: the log follows what was found. Returns (build, verdict)."""
    item, bad = check_item(raw, state)
    if bad:
        return None, bad
    if state.items[item] != "build":
        return None, Verdict(Kind.REJECT, (f"{item} is not a build; only builds carry a config.",))
    recorded = state.configs.get(item)
    if check and recorded is None:
        return None, Verdict(Kind.REJECT, (f"No config recorded for {item} yet, so nothing to "
                                           f"check against. `field-ledger cfg {item} <file>` "
                                           f"records one.",))
    if recorded and recorded.dst == digest:
        what = "matches the record" if check else "is already recorded"
        return item, Verdict(Kind.IGNORE, (f"{item}'s config {what} ({digest[:8]}).",))
    if check:
        return item, Verdict(Kind.WARN, (f"{item}'s config at the site is not the one recorded: "
                                         f"recorded {recorded.dst[:8]}, found {digest[:8]}. "
                                         f"A mismatch.",), ("mismatch",))
    return item, Verdict(Kind.ACCEPT)


def validate_owner(actor: str, to: str, people: list[str], state: State, now: datetime,
                   nudged_since: datetime | None, nudge_after: timedelta) -> tuple[str | None, Verdict]:
    """Who may write OWNER (Design Doc §3, Trust): the current owner hands over to anyone on
    the People list; with no owner yet, anyone takes it. Otherwise only a claim for yourself,
    once the owner's nudge (the oldest open ⚠, `nudged_since`) has gone unanswered for
    `nudge_after`. Every day counts. Returns (the new owner as the list spells it, verdict)."""
    name = next((p for p in people if p.casefold() == " ".join(to.split()).casefold()), None)
    if name is None:
        return None, Verdict(Kind.REJECT, (f"'{to}' isn't on the People list.",))
    current = state.owner.dst if state.owner else ""
    if name == current:
        return None, Verdict(Kind.IGNORE, (f"{name} is already the field-ops owner.",))
    if not current or actor == current:
        return name, Verdict(Kind.ACCEPT)
    if name != actor:
        return None, Verdict(Kind.REJECT, (f"Only {current} can hand the field-ops owner over.",))
    waited = now - nudged_since if nudged_since else None
    if waited is None or waited < nudge_after:
        when = (f" A ⚠ has waited {hours(waited)}; after {hours(nudge_after)}, anyone can take over."
                if waited is not None else " Anyone can take over once a ⚠ nudge goes unanswered.")
        return None, Verdict(Kind.REJECT, (f"Only {current} can hand the field-ops owner over.{when}",))
    return name, Verdict(Kind.WARN, (f"{current} left a ⚠ unanswered for {hours(waited)}: "
                                     f"{name} takes over.",), ("claimed",))


def hours(span: timedelta) -> str:
    return f"{int(span.total_seconds() // 3600)} h"


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
    if no_owner := check_owner(state):
        return None, "", no_owner
    return item, pick, Verdict(Kind.ACCEPT)


def validate_deploy(branch: str, dst: str, state: State) -> Verdict:
    """A deploy is a move of a branch node, except that the node may not exist yet, so
    `check_item` does not apply. Everything else about a move does."""
    bad = check_owner(state) or check_container(dst, state)
    if bad:
        return bad
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
