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
from datetime import datetime
from pathlib import Path

from . import store
from .importer import extract_commands, import_ids
from .kit import PlannedAdd
from .model import Event, Kind, Move, Rename, Verdict, Void
from .parse import ParseError, parse
from .state import State, fold
from .validate import canonical_destination, validate_move, validate_rename, validate_void


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


def import_line(ctx: Context, line_no: int, text: str, event_id: str, known: set[str]) -> ImportLine:
    if event_id in known:
        return ImportLine(line_no, text, "already-imported")
    try:
        cmd = parse(text)
    except ParseError as err:
        return ImportLine(line_no, text, "rejected", (str(err),))
    outcome = submit_any(ctx, cmd, event_id, ("unconfirmed-import",))
    status = import_status(outcome)
    if status == "ignored":          # remember it; rejected lines stay retryable (e.g. after `fl add`)
        store.mark_skipped(ctx.conn, event_id)
    return ImportLine(line_no, text, status, outcome.verdict.messages)


def import_text(ctx: Context, text: str) -> list[ImportLine]:
    commands = extract_commands(text)
    known = store.existing_ids(ctx.conn)
    return [import_line(ctx, n, line, eid, known)
            for (n, line), eid in zip(commands, import_ids(ctx.actor, commands))]


def flagged_events(state: State) -> list[Event]:
    return [e for e in reversed(state.events) if e.flags]

