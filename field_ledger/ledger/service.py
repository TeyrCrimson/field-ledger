"""Validate-then-write. The only module that both decides and touches the database.

The CLI and the (future) web page are thin adapters over these functions, so they
accept and reject exactly the same inputs.

CONFIRM is two-phase: the first call writes nothing and returns the CONFIRM verdict;
the caller asks the person, then calls again with confirmed=True.
"""

import hashlib
import sqlite3
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

from . import store
from .ids import canonical_location
from .importer import extract_commands, import_ids, repeats
from .kit import PlannedAdd
from .model import Event, Kind, Move, Rename, Verdict, Void
from .parse import ParseError, parse
from .state import (State, audit_due, clock, conflict_starts, conflicts, fold, location_of,
                    mismatches)
from .validate import (canonical_destination, check_id_destination, combine, node_id,
                       validate_deploy,
                       validate_audit, validate_config, validate_label, validate_owner,
                       validate_state,
                       validate_move, validate_rename, validate_resolve, validate_void)

UNDO_WINDOW = timedelta(minutes=10)      # `undo_minutes`, until settings are a thing
CONFLICT_WINDOWS = (timedelta(minutes=5), timedelta(minutes=60))   # `conflict_window`: device, import
# A phone clock this far ahead of the hub's is wrong, not early: its event is flagged `future`.
# The device conflict window: a phone fast by less can only reorder moves that would ⚠ anyway.
FUTURE_TOLERANCE = timedelta(minutes=5)
NUDGE_AFTER = timedelta(days=1)          # `nudge_after`: every day counts (Teyr, 2026-10-30)


@dataclass
class Context:
    conn: sqlite3.Connection
    actor: str
    device: str
    now: Callable[[], datetime]
    ledger_dir: Path                # the record; `conn` is its cache, synced on open
    batch: str = ""                 # set while one command writes several events
    time_source: str = ""           # 'import' while importing a chat export
    occurred_at: datetime | None = None   # a phone's own time for its write; else now()
    seq: int | None = None          # a phone's own count of its writes; else the next one here


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
    """The replay, plus which kinds hold things and their states (settings, not events)."""
    state = fold(store.load(ctx.conn))
    state.containers = store.read_containers(ctx.ledger_dir)
    state.kind_states = store.read_kind_states(ctx.ledger_dir)
    return state


def deployed_at(ctx: Context, item: str) -> str:
    """Where a node is now, or '' if it has never been placed. For the readback's
    'was in ...', which has to be read before the move is written."""
    return location_of(current_state(ctx), item)


def occurred(ctx: Context) -> datetime:
    return ctx.occurred_at or ctx.now()


def make_event(ctx: Context, kind: str, event_id: str | None = None, ahead: int = 0,
               flags: tuple[str, ...] = (), **fields) -> Event:
    """`ahead` reserves seqs for events built in one batch before any of them is written.
    A phone's events keep the time and seq it gave them, so a write that waited in its queue
    still sorts where it happened; the hub's own clock goes in recorded_at."""
    now = ctx.now()
    if occurred(ctx) - now > FUTURE_TOLERANCE:
        flags += ("future",)
    seq = ctx.seq if ctx.seq is not None else store.next_seq(ctx.conn, ctx.device)
    return Event(id=event_id or str(uuid.uuid4()), ts=occurred(ctx), recorded_at=now,
                 device=ctx.device, seq=seq + ahead, actor=ctx.actor, kind=kind,
                 batch=ctx.batch, time_source=ctx.time_source, flags=flags, **fields)


def one_command(ctx: Context) -> Context:
    """Everything written through the returned context is one command to undo."""
    return replace(ctx, batch=str(uuid.uuid4()))


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
    item, verdict = validate_move(cmd, ctx.actor, state, occurred(ctx))
    if not should_write(verdict, confirmed):
        return Outcome(verdict)
    # src is where the log last had it, not the typed 'from': that was checked above
    return write(ctx, verdict, "MOVE", event_id, extra_flags, item=item,
                 src=state.where.get(item, ""), dst=canonical_destination(cmd.dst, state))


def submit_deploy(ctx: Context, branch: str, dst: str, sha: str = "",
                  confirmed: bool = False) -> Outcome:
    """Code mode: a build is a node of kind `build`, named after its branch, and its
    parent is where it is deployed.

    The build node and the destination node are created on first use, in the same
    commit as the move, so a deploy is one thing in the log. A destination that is
    already a node (a location node, or an item like DRN-03) is used as it stands; a
    plain-string location from an older ledger stays a plain string.

    A new build starts at `build_home` (a setting, default 'hq'): code comes from
    somewhere too, so its first deploy has a real 'from' like any other move.
    """
    ctx, state = one_command(ctx), current_state(ctx)
    shape = check_id_destination(dst, state)
    if shape and shape.kind == Kind.REJECT:
        return Outcome(shape)
    target = node_id(dst, state) or canonical_location(dst)
    verdict = combine([shape, validate_deploy(branch, target, state)])
    if not should_write(verdict, confirmed):
        return Outcome(verdict)
    home = canonical_destination(store.read_settings(ctx.ledger_dir)["build_home"], state)
    src = state.where.get(branch, home)
    new = []
    for place in dict.fromkeys([src, target]):      # home first, then the target
        if place not in state.items and place not in state.locations:
            new.append(make_event(ctx, "ADD", ahead=len(new), item=place, note="location",
                                  flags=("fixed",)))
    if branch not in state.items:
        new.append(make_event(ctx, "ADD", ahead=len(new), item=branch, dst=home, note="build"))
    confirmed_flag = ("confirmed",) if verdict.kind == Kind.CONFIRM else ()
    move = make_event(ctx, "MOVE", ahead=len(new), item=branch, src=src, dst=target, sha=sha,
                      flags=verdict.flags + confirmed_flag)
    store.add(ctx.conn, ctx.ledger_dir, new + [move])
    return Outcome(verdict, move)


def submit_label(ctx: Context, branch: str, label: str, reason: str = "",
                 event_id: str | None = None) -> Outcome:
    """SEC: a build's security label, set by hand (no scanner). Latest wins, and a VOID
    of it brings the previous label back, because replay skips voided events."""
    item, label, verdict = validate_label(branch, label, current_state(ctx))
    if item is None:
        return Outcome(verdict)
    return write(ctx, verdict, "SEC", event_id, (), item=item, dst=label, note=reason)


def submit_state(ctx: Context, item: str, value: str, reason: str = "",
                 event_id: str | None = None) -> Outcome:
    """STATE: what shape a piece of kit is in (a battery depleted), separate from where it
    is, so a move never changes a state and a state never moves anything. Latest wins."""
    item, value, verdict = validate_state(item, value, current_state(ctx))
    if item is None:
        return Outcome(verdict)
    return write(ctx, verdict, "STATE", event_id, (), item=item, dst=value, note=reason)


def day_start(now: datetime) -> datetime:
    """A deployment day starts at local midnight on the machine asking (the hub, or the laptop
    running `fl`). Every day counts, as with kit left in a vehicle."""
    return now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)


def audit_report(state: State, now: datetime) -> tuple[list[str], list[Event]]:
    """(what's due, today's mismatches): the audit screen and `fl audit` read the same."""
    since = day_start(now)
    return audit_due(state, since), mismatches(state, since)


def submit_audit(ctx: Context, item: str, found: str = "", confirmed: bool = False,
                 event_id: str | None = None) -> Outcome:
    """AUD: one item checked at the end-of-day audit. Only the board's audit screen writes
    it (never a typed command), so a check never poses as a move and a move never as a check.
    Found where the log has it: the location stays. Found elsewhere or missing: it's put
    there, and it counts as a mismatch."""
    state = current_state(ctx)
    item, found, verdict = validate_audit(item, found, state)
    if item is None or not should_write(verdict, confirmed):
        return Outcome(verdict)
    return write(ctx, verdict, "AUD", event_id, (), item=item, src=state.where.get(item, ""),
                 dst=found)


def config_digest(contents: list[bytes]) -> str:
    """The SHA-256 the ledger keeps for a config, always computed here from the config's own
    bytes: no command, import line or hub request carries a hash, so none can be spoofed
    (Teyr, 2026-10-30). One file: its plain SHA-256, what `sha256sum` prints, so anyone can
    check it by hand. Several (a chart and its values): the SHA-256 of their sorted
    digests, so only the bytes count, not the order or the file names. A copy pulled off
    the device under another name still matches."""
    digests = sorted(hashlib.sha256(data).hexdigest() for data in contents)
    if len(digests) == 1:
        return digests[0]
    return hashlib.sha256("\n".join(digests).encode()).hexdigest()


def read_config(ref: str, repo: Path) -> tuple[str, bytes]:
    """(how the record names it, its bytes). `path` is a file on this laptop; `path@rev` is
    that file in the code repo at a commit, named by the full commit id so the record points
    at one exact version. Raises ValueError if it can't be read."""
    path, at, rev = ref.rpartition("@")
    if not (at and path):           # ponytail: a file name with '@' in it reads as path@rev
        file = Path(ref)
        if not file.is_file():
            raise ValueError(f"No file '{ref}'.")
        return ref, file.read_bytes()
    if rev.startswith("-"):
        raise ValueError(f"'{rev}' is not a commit.")
    found = subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify", "--quiet",
                            f"{rev}^{{commit}}"], capture_output=True, text=True)
    if found.returncode != 0:
        raise ValueError(f"No commit '{rev}' in {repo}.")
    commit = found.stdout.strip()
    shown = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{path}"], capture_output=True)
    if shown.returncode != 0:
        raise ValueError(f"No file '{path}' at {commit[:7]} in {repo}.")
    return f"{path}@{commit}", shown.stdout


def submit_config(ctx: Context, build: str, refs: list[str], repo: Path, reason: str = "",
                  check: bool = False) -> Outcome:
    """CFG: a build's config, as a hash this function computes from the files. Recording a new
    one logs what changed after deploying to the location. A check compares a copy of what's
    deployed with the record, and a difference is written as a CFG flagged `mismatch`."""
    try:
        read = [read_config(ref, repo) for ref in refs]
    except ValueError as error:
        return Outcome(Verdict(Kind.REJECT, (str(error),)))
    digest = config_digest([data for _, data in read])
    item, verdict = validate_config(build, digest, current_state(ctx), check)
    if item is None or not should_write(verdict, False):
        return Outcome(verdict)
    return write(ctx, verdict, "CFG", None, (), item=item,
                 src=" + ".join(name for name, _ in read), dst=digest, note=reason)


def nudged_since(state: State, windows: tuple[timedelta, timedelta] = CONFLICT_WINDOWS
                 ) -> datetime | None:
    """When the owner's nudge began: the oldest open ⚠, or when this owner took over if
    that was later (a new owner gets their own full day). None when there's nothing to
    settle. Worked out on every read; nothing is written for it."""
    oldest = min(conflict_starts(state, *windows).values(), default=None)
    if oldest and state.owner:
        return max(oldest, clock(state.owner))
    return oldest


def owner_report(state: State, now: datetime) -> dict:
    """The field-ops owner and their nudge, as `fl owner` and the board show it."""
    since = nudged_since(state)
    return {"name": state.owner.dst if state.owner else "",
            "since": state.owner.ts.isoformat() if state.owner else None,
            "open": len(conflicts(state, *CONFLICT_WINDOWS)),
            "nudged_since": since.isoformat() if since else None,
            "claimable": bool(state.owner and since and now - since >= NUDGE_AFTER)}


def submit_owner(ctx: Context, to: str, event_id: str | None = None) -> Outcome:
    """OWNER: hand the field-ops owner over, take it when there's none, or claim it after an
    unanswered nudge. An ordinary, attributed event either way."""
    state = current_state(ctx)
    name, verdict = validate_owner(ctx.actor, to, store.read_people(ctx.ledger_dir), state,
                                   ctx.now(), nudged_since(state), NUDGE_AFTER)
    if name is None:
        return Outcome(verdict)
    return write(ctx, verdict, "OWNER", event_id, (),
                 src=state.owner.dst if state.owner else "", dst=name)


def open_conflicts(state: State, windows: tuple[timedelta, timedelta] = CONFLICT_WINDOWS
                   ) -> dict[str, tuple[str, str]]:
    return conflicts(state, *windows)


def submit_resolve(ctx: Context, item: str, pick: str,
                   windows: tuple[timedelta, timedelta] = CONFLICT_WINDOWS,
                   event_id: str | None = None) -> Outcome:
    """RESOLVE: confirm one candidate of a ⚠. Picking the other one moves the node there."""
    state = current_state(ctx)
    item, pick, verdict = validate_resolve(item, pick, state, conflicts(state, *windows))
    if item is None:
        return Outcome(verdict)
    return write(ctx, verdict, "RESOLVE", event_id, (), item=item, src=state.where.get(item, ""),
                 dst=pick)


def used_since(state: State, node: str, command: list[Event]) -> bool:
    """Someone has moved, filled or named `node` outside this command: their event needs it."""
    ids = {e.id for e in command}
    return any(e.id not in ids and node in (e.item, e.src, e.dst) for e in state.events)


def submit_undo(ctx: Context, within: timedelta = UNDO_WINDOW,
                event_id: str | None = None) -> Outcome:
    """Undo takes back your own last command, offered for `within` only.

    One command can write several events (a deploy's new nodes and its move, a kit, a
    whole import); they share a batch and are voided together, in one commit. A node the
    command created that someone has used since is left alone: their event needs it.
    After the window the events have been read by someone else and a bare undo is no
    longer honest: `void <id> <reason>` says why. The window starts when the event reached
    the ledger, so a write that waited in a phone's queue can still be undone on arrival.
    """
    state = current_state(ctx)
    target = next((e for e in reversed(state.events)
                   if e.actor == ctx.actor and e.kind != "VOID"), None)
    if target is None:
        return Outcome(Verdict(Kind.REJECT, ("Nothing of yours left to undo.",)))
    age = ctx.now() - (target.recorded_at or target.ts)
    if age > within:
        return Outcome(Verdict(Kind.REJECT, (
            f"{target.id[:8]} is {int(age.total_seconds() // 60)} minutes old; undo is only "
            f"offered for {int(within.total_seconds() // 60)}. "
            f"Use `void {target.id[:8]} <reason>`.",)))
    command = [e for e in state.events if e.actor == ctx.actor and e.kind != "VOID"
               and (e.id == target.id or (target.batch and e.batch == target.batch))]
    kept = sorted({e.item for e in command
                   if e.kind == "ADD" and used_since(state, e.item, command)})
    undone = [e for e in command if not (e.kind == "ADD" and e.item in kept)]
    ids = batch_ids(event_id, len(undone))        # a resent undo must not undo the one before
    voids = [make_event(ctx, "VOID", ids[n], ahead=n, ref=e.id, note="undo")
             for n, e in enumerate(undone)]
    store.add(ctx.conn, ctx.ledger_dir, voids)
    messages = ((f"Took back {len(voids)} events from one command.",) if len(voids) > 1 else ())
    messages += tuple(f"Kept {node}: used since by someone else." for node in kept)
    return Outcome(Verdict(Kind.WARN if kept else Kind.ACCEPT, messages), voids[-1])


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


def batch_ids(first: str | None, count: int) -> list[str | None]:
    """The given id for the first event, the rest derived from it: the same ids every time."""
    if not first:
        return [None] * count
    return [first] + [str(uuid.uuid5(uuid.UUID(first), str(n))) for n in range(1, count)]


def add_items(ctx: Context, planned: list[PlannedAdd], event_id: str | None = None) -> list[Event]:
    """Kit creation. Items already in the kit are skipped (kit loading is re-runnable).
    A phone names the first event; the rest are derived from it, so a resend is spotted."""
    ctx, existing = one_command(ctx), set(current_state(ctx).items)
    new = [p for p in planned if p.item not in existing]
    ids = batch_ids(event_id, len(new))
    written = [make_event(ctx, "ADD", ids[n], ahead=n, item=p.item, dst=p.location, note=p.name)
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
    """One import is one command: undo takes the whole file back."""
    ctx, commands = replace(one_command(ctx), time_source="import"), extract_commands(text)
    known = store.existing_ids(ctx.conn)
    repeated = repeats(commands)
    return [import_line(ctx, n, line, eid, known, repeated.get(n))
            for (n, line), eid in zip(commands, import_ids(text, commands))]


def flagged_events(state: State) -> list[Event]:
    return [e for e in reversed(state.events) if e.flags]

