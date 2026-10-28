"""Events -> current state. A pure fold: same events in, same state out.

Latest wins: across devices by timestamp, within one device by seq (see `ordered`).
Voided events are skipped entirely. Location renames apply retroactively at read
time: the stored events keep the text exactly as typed, and the view shows the
corrected name.

Contents follow their container. An item's `where` is its immediate parent, which
can be another item (BAT-01 in CAS-01); its location is found by walking up. So
moving a case is one event, and everything inside it has moved too.

A node flagged `fixed` is a location: it holds nodes and has nothing above it. Older
ledgers name locations with a plain string instead, which still works: `where` holds
whichever it was given, and anything not an item is treated as the top of the chain.
"""

from dataclasses import dataclass, field
from datetime import timedelta

from .model import Event


@dataclass
class State:
    items: dict[str, str] = field(default_factory=dict)        # item -> group name
    where: dict[str, str] = field(default_factory=dict)        # item -> parent: location or item
    last_event: dict[str, Event] = field(default_factory=dict) # item -> latest ADD/MOVE
    locations: set[str] = field(default_factory=set)           # every resolved location seen
    fixed: set[str] = field(default_factory=set)               # location nodes: hold nodes, rarely move
    aliases: dict[str, str] = field(default_factory=dict)      # old location -> new
    labels: dict[str, str] = field(default_factory=dict)       # build -> security label (SEC)
    containers: set[str] = field(default_factory=set)          # kinds that hold things (settings)
    chain_before: dict[str, list[str]] = field(default_factory=dict)  # move id -> item's ancestors then
    carried: dict[str, set[str]] = field(default_factory=dict)  # move id -> every node it moved
    voided: set[str] = field(default_factory=set)
    events: list[Event] = field(default_factory=list)          # live (non-voided) events, in order


def ordered(events: list[Event]) -> list[Event]:
    """Oldest first. A device's clock can jump back but its seq counter can't, so each
    event's effective time is never earlier than its device's previous event."""
    effective, last = {}, {}
    for e in sorted(events, key=lambda e: (e.device, e.seq)):
        last[e.device] = effective[e.id] = max(e.ts, last.get(e.device, e.ts))
    return sorted(events, key=lambda e: (effective[e.id], e.device, e.seq))


def voided_ids(events: list[Event]) -> set[str]:
    return {e.ref for e in events if e.kind == "VOID"}


def resolve(location: str, aliases: dict[str, str]) -> str:
    """Follow rename chains (a -> b -> c). Stops on a cycle instead of looping."""
    seen = set()
    while location in aliases and location not in seen:
        seen.add(location)
        location = aliases[location]
    return location


def ancestors(state: State, node: str) -> list[str]:
    """Everything above `node`, innermost first: BAT-01 in CAS-01 in van -> [CAS-01, van].
    Stops on a cycle instead of looping."""
    chain: list[str] = []
    while node in state.where:
        node = state.where[node]
        if node in chain:
            break
        chain.append(node)
    return chain


def makes_cycle(state: State, item: str, dst: str) -> bool:
    """Putting `item` into `dst` would put it inside itself."""
    return dst == item or item in ancestors(state, dst)


def location_of(state: State, item: str) -> str:
    """Top of the chain. '' for a node that has not been placed anywhere yet."""
    chain = ancestors(state, item)
    return chain[-1] if chain else ""


def apply(state: State, event: Event) -> None:
    """Apply one live event. Location fields are stored raw; resolved in `finish`."""
    if event.kind == "ADD":
        state.items[event.item] = event.note
        if "fixed" in event.flags:
            state.fixed.add(event.item)
    # ponytail: a cycle can only arrive from two offline devices; it is skipped here
    # (the event stays in the log, voidable) until the conflicts view can show it.
    moves = event.kind in ("MOVE", "RESOLVE") and not makes_cycle(state, event.item, event.dst)
    if moves:                           # the ⚠ rule needs what each move saw and carried
        state.chain_before[event.id] = ancestors(state, event.item)
        state.carried[event.id] = {event.item} | {
            n for n in state.where if event.item in ancestors(state, n)}
    # An ADD with no destination is a node with nothing above it yet: a location, or a
    # branch waiting for its first deploy. It stays out of `where` so it has no parent.
    if (event.kind == "ADD" and event.dst) or moves:
        state.where[event.item] = event.dst
        state.last_event[event.item] = event
        if event.dst not in state.items:
            state.locations.add(event.dst)
    elif event.kind == "RENAME":
        state.aliases[event.src] = event.dst
    elif event.kind == "SEC":           # latest wins; a voided one never gets here
        state.labels[event.item] = event.dst
    state.events.append(event)


def conflicts(state: State, device_window: timedelta,
              import_window: timedelta) -> dict[str, tuple[str, str]]:
    """Node -> (where the log has it, the other candidate): README "When two moves disagree".

    Two live moves conflict on a node when both affect its location (directly, or by
    moving a container it was in), within the window (the wider one if either time is
    import/prompted), to different places, from different devices or with either time
    approximate. Same destination is a duplicate; one device's own moves are ordered by
    its seq. A later move or a RESOLVE of the node settles it: latest wins again.
    Pure, computed on every replay, never stored. The windows are passed in.
    """
    # ponytail: pairwise over moves, O(n²); index moves by node if ledgers get big
    moves = [e for e in state.events if e.kind == "MOVE" and e.id in state.carried]
    found: dict[str, tuple[int, str, str]] = {}           # node -> (index of later move, a, b)
    for i, a in enumerate(moves):
        for j in range(i + 1, len(moves)):
            b = moves[j]
            loose = {a.time_source, b.time_source} & {"import", "prompted"}
            if abs(b.ts - a.ts) > (import_window if loose else device_window):
                continue
            if a.device == b.device and not loose:
                continue
            if resolve(a.dst, state.aliases) == resolve(b.dst, state.aliases):
                continue
            shared = state.carried[a.id] & state.carried[b.id]
            if b.item in state.chain_before[a.id]:      # b moved the container a's item was in
                shared.add(a.item)
            if a.item in state.chain_before[b.id]:
                shared.add(b.item)
            for node in shared:
                found[node] = (state.events.index(b), placed_by(a, node), placed_by(b, node))
    settled = {e.item: k for k, e in enumerate(state.events) if e.kind in ("MOVE", "RESOLVE")}
    result = {}
    for node, (k, one, two) in found.items():
        if settled.get(node, -1) > k:                   # moved or resolved since
            continue
        here = state.where.get(node, "")
        other = one if resolve(one, state.aliases) != here else two
        if resolve(other, state.aliases) != here:
            result[node] = (here, resolve(other, state.aliases))
    return result


def deployed_sha(state: State, build: str) -> str:
    """The commit on the build's latest live move ('' if unknown). A RESOLVE only
    confirms a place, so it never stands in for a deploy."""
    return next((e.sha for e in reversed(state.events)
                 if e.kind == "MOVE" and e.item == build), "")


def placed_by(move: Event, node: str) -> str:
    """Where `move` puts `node`: its destination, or (moving a container) still inside it."""
    return move.dst if move.item == node else move.item


def finish(state: State) -> State:
    """Push every location through the rename table."""
    state.where = {item: resolve(loc, state.aliases) for item, loc in state.where.items()}
    state.locations = {resolve(loc, state.aliases) for loc in state.locations}
    return state


def fold(events: list[Event]) -> State:
    state = State(voided=voided_ids(events))
    for event in ordered(events):
        if event.id not in state.voided:
            apply(state, event)
    return finish(state)


def items_at(state: State, location: str) -> list[str]:
    """Everything at a location or inside a container, however deep."""
    target = resolve(location, state.aliases)
    return sorted(item for item in state.where if target in ancestors(state, item))
