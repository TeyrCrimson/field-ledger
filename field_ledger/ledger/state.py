"""Events -> current state. A pure fold: same events in, same state out.

Latest wins: across devices by timestamp, within one device by seq (see `ordered`).
Voided events are skipped entirely. Location renames apply retroactively at read
time: the stored events keep the text exactly as typed, and the view shows the
corrected name.

Contents follow their container. An item's `where` is its immediate parent, which
can be another item (BAT-01 in CAS-01); its location is found by walking up. So
moving a case is one event, and everything inside it has moved too.
"""

from dataclasses import dataclass, field

from .model import Event


@dataclass
class State:
    items: dict[str, str] = field(default_factory=dict)        # item -> group name
    where: dict[str, str] = field(default_factory=dict)        # item -> parent: location or item
    last_event: dict[str, Event] = field(default_factory=dict) # item -> latest ADD/MOVE
    locations: set[str] = field(default_factory=set)           # every resolved location seen
    aliases: dict[str, str] = field(default_factory=dict)      # old location -> new
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
    return ancestors(state, item)[-1]


def apply(state: State, event: Event) -> None:
    """Apply one live event. Location fields are stored raw; resolved in `finish`."""
    # ponytail: a cycle can only arrive from two offline devices; it is skipped here
    # (the event stays in the log, voidable) until the conflicts view can show it.
    moves = event.kind == "MOVE" and not makes_cycle(state, event.item, event.dst)
    if event.kind == "ADD" or moves:
        if event.kind == "ADD":
            state.items[event.item] = event.note
        state.where[event.item] = event.dst
        state.last_event[event.item] = event
        if event.dst not in state.items:
            state.locations.add(event.dst)
    elif event.kind == "RENAME":
        state.aliases[event.src] = event.dst
    state.events.append(event)


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
