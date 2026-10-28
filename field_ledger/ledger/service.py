"""Validate-then-write. The only module that both decides and touches the database.

The CLI and the (future) web page are thin adapters over these functions, so they
accept and reject exactly the same inputs.

CONFIRM is two-phase: the first call writes nothing and returns the CONFIRM verdict;
the caller asks the person, then calls again with confirmed=True.
"""

import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import store
from .ids import canonical_location
from .importer import extract_commands, import_ids, repeats
from .kit import PlannedAdd
from .model import Event, Kind, Move, Rename, Verdict, Void
from .parse import ParseError, parse
from .state import State, fold, location_of
from .validate import (canonical_destination, node_id, validate_deploy, validate_move,
                       validate_rename, validate_void)

UNDO_WINDOW = timedelta(minutes=10)      # `undo_minutes`, until settings are a thing


@dataclass
class Context:
    conn: sqlite3.Connection
    actor: str
    device: str
    now: Callable[[], datetime]
    ledger_dir: Path                # the record; `conn` is its cache, synced on open


@dataclass(frozen=True)
class Outcome:
    verdict: Verdict
    event: Event | None = None      # set only if something was written


@dataclass(frozen=True)
class ImportLine:
    line_no: int
    text: str
    status: str                     # written | flagged | already-imported | ignored | rejected
    messages: tuple[str, ...] = field(default=())


def current_state(ctx: Context) -> State:
    return fold(store.load(ctx.conn))


def deployed_at(ctx: Context, item: str) -> str:
    """Where a node is now, or '' if it has never been placed. For the readback's
    'was in ...', which has to be read before the move is written."""
    return location_of(current_state(ctx), item)


def make_event(ctx: Context, kind: str, event_id: str | None = None, ahead: int = 0,
               **fields) -> Event:
    """`ahead` reserves seqs for events built in one batch before any of them is written."""
    return Event(id=event_id or str(uuid.uuid4()), ts=ctx.now(), device=ctx.device,
                 seq=store.next_seq(ctx.conn, ctx.device) + ahead, actor=ctx.actor, kind=kind,
                 **fields)


def should_write(verdict: Verdict, confirmed: bool) -> bool:
    if verdict.kind in (Kind.REJECT, Kind.IGNORE):
        return False
    return verdict.kind != Kind.CONFIRM or confirmed


def write(ctx: Context, verdict: Verdict, kind: str, event_id: str | None,
          extra_flags: tuple[str, ...], **fields) -> Outcome:
    confirmed_flag = ("confirmed",) if verdict.kind == Kind.CONFIRM else ()
    event = make_event(ctx, kind, event_id, flags=verdict.flags + confirmed_flag + extra_flags,
                       **fields)
    store.add(ctx.conn, ctx.ledger_dir, [event])
    return Outcome(verdict, event)


# --- commands that write -------------------------------------------------------

def submit_move(ctx: Context, cmd: Move, confirmed: bool = False,
                event_id: str | None = None, extra_flags: tuple[str, ...] = ()) -> Outcome:
    state = current_state(ctx)
    item, verdict = validate_move(cmd, ctx.actor, state, ctx.now())
    if not should_write(verdict, confirmed):
        return Outcome(verdict)
    return write(ctx, verdict, "MOVE", event_id, extra_flags, item=item,
                 src=canonical_destination(cmd.src, state),
                 dst=canonical_destination(cmd.dst, state))


def submit_deploy(ctx: Context, branch: str, dst: str, sha: str = "",
                  confirmed: bool = False) -> Outcome:
    """Code mode: a build is a node of kind `build`, named after its branch, and its
    parent is where it is deployed.

    The build node and the destination node are created on first use, in the same
    commit as the move, so a deploy is one thing in the log. A destination that is
    already a node (a location node, or an item like DRN-03) is used as it stands; a
    plain-string location from an older ledger stays a plain string.
    """
    state = current_state(ctx)
    target = node_id(dst, state) or canonical_location(dst)
    verdict = validate_deploy(branch, target, state)
    if not should_write(verdict, confirmed):
        return Outcome(verdict)
    new = []
    if target not in state.items and target not in state.locations:
        new.append(make_event(ctx, "ADD", ahead=len(new), item=target, note="location",
                              flags=("fixed",)))
    if branch not in state.items:
        new.append(make_event(ctx, "ADD", ahead=len(new), item=branch, note="build"))
    confirmed_flag = ("confirmed",) if verdict.kind == Kind.CONFIRM else ()
    # src: its parent before the move, so the log can say where it came from
    move = make_event(ctx, "MOVE", ahead=len(new), item=branch,
                      src=state.where.get(branch, ""), dst=target, sha=sha,
                      flags=verdict.flags + confirmed_flag)
    store.add(ctx.conn, ctx.ledger_dir, new + [move])
    return Outcome(verdict, move)


def submit_undo(ctx: Context, within: timedelta = UNDO_WINDOW) -> Outcome:
    """Undo is a VOID of your own last event, offered for `within` only.

    After that the event has been read by someone else and a bare undo is no longer
    honest: `void <id> <reason>` says why.
    """
    state = current_state(ctx)
    target = next((e for e in reversed(state.events)
                   if e.actor == ctx.actor and e.kind != "VOID"), None)
    if target is None:
        return Outcome(Verdict(Kind.REJECT, ("Nothing of yours left to undo.",)))
    age = ctx.now() - target.ts
    if age > within:
        return Outcome(Verdict(Kind.REJECT, (
            f"{target.id[:8]} is {int(age.total_seconds() // 60)} minutes old; undo is only "
            f"offered for {int(within.total_seconds() // 60)}. "
            f"Use `void {target.id[:8]} <reason>`.",)))
    return submit_void(ctx, Void(target.id, "undo"))


def submit_void(ctx: Context, cmd: Void, event_id: str | None = None,
                extra_flags: tuple[str, ...] = ()) -> Outcome:
    target, verdict = validate_void(cmd, current_state(ctx))
    if not should_write(verdict, False):
        return Outcome(verdict)
    return write(ctx, verdict, "VOID", event_id, extra_flags, ref=target, note=cmd.reason)


def submit_rename(ctx: Context, cmd: Rename, event_id: str | None = None,
                  extra_flags: tuple[str, ...] = ()) -> Outcome:
    names, verdict = validate_rename(cmd, current_state(ctx))
    if not should_write(verdict, False):
        return Outcome(verdict)
    return write(ctx, verdict, "RENAME", event_id, extra_flags, src=names[0], dst=names[1])


def add_items(ctx: Context, planned: list[PlannedAdd]) -> list[Event]:
    """Kit creation. Items already in the kit are skipped (kit loading is re-runnable)."""
    existing = set(current_state(ctx).items)
    new = [p for p in planned if p.item not in existing]
    written = [make_event(ctx, "ADD", ahead=n, item=p.item, dst=p.location, note=p.name)
               for n, p in enumerate(new)]
    store.add(ctx.conn, ctx.ledger_dir, written)      # one commit for the whole kit
    return written


# --- import --------------------------------------------------------------------

def submit_any(ctx: Context, cmd, event_id: str, extra_flags: tuple[str, ...]) -> Outcome:
    if isinstance(cmd, Move):
        first = submit_move(ctx, cmd, False, event_id)
        if first.verdict.kind == Kind.CONFIRM:   # nobody to ask: write it, mark it
            return submit_move(ctx, cmd, True, event_id, extra_flags)
        return first
    if isinstance(cmd, Void):
        return submit_void(ctx, cmd, event_id)
    return submit_rename(ctx, cmd, event_id)


def import_status(outcome: Outcome) -> str:
    if outcome.event is not None:
        return "flagged" if outcome.event.flags else "written"
    return "ignored" if outcome.verdict.kind == Kind.IGNORE else "rejected"


def import_line(ctx: Context, line_no: int, text: str, event_id: str, known: set[str],
                repeat_of: int | None) -> ImportLine:
    if event_id in known:
        return ImportLine(line_no, text, "already-imported")
    if repeat_of is not None:
        return ImportLine(line_no, text, "ignored", (f"Repeats line {repeat_of}.",))
    try:
        cmd = parse(text)
    except ParseError as err:
        return ImportLine(line_no, text, "rejected", (str(err),))
    outcome = submit_any(ctx, cmd, event_id, ("unconfirmed-import",))
    return ImportLine(line_no, text, import_status(outcome), outcome.verdict.messages)


def import_text(ctx: Context, text: str) -> list[ImportLine]:
    commands = extract_commands(text)
    known = store.existing_ids(ctx.conn)
    repeated = repeats(commands)
    return [import_line(ctx, n, line, eid, known, repeated.get(n))
            for (n, line), eid in zip(commands, import_ids(text, commands))]


def flagged_events(state: State) -> list[Event]:
    return [e for e in reversed(state.events) if e.flags]

