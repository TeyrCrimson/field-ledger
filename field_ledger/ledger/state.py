"""Events -> current state. A pure fold: same events in, same state out.

Ordering is (timestamp, device, seq). Voided events are skipped entirely.
Location renames apply retroactively at read time: the stored events keep the
text exactly as typed, and the view shows the corrected name.
"""

from dataclasses import dataclass, field

from .model import Event


@dataclass
class State:
    items: dict[str, str] = field(default_factory=dict)        # item -> group name
    where: dict[str, str] = field(default_factory=dict)        # item -> location (resolved)
    last_event: dict[str, Event] = field(default_factory=dict) # item -> latest ADD/MOVE
    locations: set[str] = field(default_factory=set)           # every resolved location seen
    aliases: dict[str, str] = field(default_factory=dict)      # old location -> new
    voided: set[str] = field(default_factory=set)
    events: list[Event] = field(default_factory=list)          # live (non-voided) events, in order


def order_key(event: Event) -> tuple:
    return (event.ts, event.device, event.seq)


def voided_ids(events: list[Event]) -> set[str]:
    return {e.ref for e in events if e.kind == "VOID"}


def resolve(location: str, aliases: dict[str, str]) -> str:
    """Follow rename chains (a -> b -> c). Stops on a cycle instead of looping."""
    seen = set()
    while location in aliases and location not in seen:
        seen.add(location)
        location = aliases[location]
    return location


def apply(state: State, event: Event) -> None:
    """Apply one live event. Location fields are stored raw; resolved in `finish`."""
    if event.kind in ("ADD", "MOVE"):
        if event.kind == "ADD":
            state.items[event.item] = event.note
        state.where[event.item] = event.dst
        state.last_event[event.item] = event
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
    for event in sorted(events, key=order_key):
        if event.id not in state.voided:
            apply(state, event)
    return finish(state)


def items_at(state: State, location: str) -> list[str]:
    target = resolve(location, state.aliases)
    return sorted(item for item, loc in state.where.items() if loc == target)
