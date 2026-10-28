"""Plain data types. No logic lives here."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Kind(str, Enum):
    """What the validator decided. Order of the members is not meaningful."""

    ACCEPT = "accept"    # write it
    WARN = "warn"        # write it, with flags
    CONFIRM = "confirm"  # understood but suspicious: write only if a person says yes
    REJECT = "reject"    # not understood: write nothing
    IGNORE = "ignore"    # a repeat of something already written: write nothing


@dataclass(frozen=True)
class Verdict:
    kind: Kind
    messages: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()   # stored on the event if it is written


# --- Commands: what a person asked for, already parsed but not yet validated ---

@dataclass(frozen=True)
class Move:
    item: str          # raw text, canonicalised during validation
    dst: str
    src: str = ""      # optional: where the person thinks it came from


@dataclass(frozen=True)
class Where:
    item: str


@dataclass(frozen=True)
class At:
    location: str


@dataclass(frozen=True)
class Void:
    ref: str           # event id, or a unique prefix of one
    reason: str


@dataclass(frozen=True)
class Rename:
    old: str
    new: str


Command = Move | Where | At | Void | Rename


# --- Events: what gets stored. Append-only; never edited after writing. ---

@dataclass(frozen=True)
class Event:
    id: str
    ts: datetime              # timezone-aware, UTC
    device: str
    seq: int                  # per-device counter: ordering survives clock drift on one device
    actor: str
    kind: str                 # ADD | MOVE | VOID | RENAME
    item: str = ""
    src: str = ""             # MOVE: stated origin. RENAME: old name.
    dst: str = ""             # MOVE/ADD: location. RENAME: new name.
    ref: str = ""             # VOID: target event id
    note: str = ""            # VOID: reason. ADD: group name.
    sha: str = ""             # MOVE of a build node: its head commit when it was deployed
    batch: str = ""           # shared by the events one command wrote; undo takes them back together
    flags: tuple[str, ...] = field(default=())
