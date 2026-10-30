"""`fl`: command-line adapter over `service`. Prints verdicts; never decides anything itself.

Exit codes: 0 written/ignored/query ok, 1 rejected, 2 confirmation declined.
"""

import argparse
import os
import re
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from . import service, store
from .ids import canonical_location, is_prefix
from .kit import Group, plan_kit, plan_more, read_kit
from .model import At, Event, Kind, Move, Rename, Verdict, Void, Where
from .parse import ParseError, parse
from .state import ancestors, items_at, location_of
from .validate import canonical_destination, node_id, not_found

TAG = {Kind.ACCEPT: "OK", Kind.WARN: "WARN", Kind.CONFIRM: "CONFIRM",
       Kind.REJECT: "REJECT", Kind.IGNORE: "IGNORED"}
Ask = Callable[[str], bool]


# --- rendering -----------------------------------------------------------------

def describe(e: Event) -> str:
    if e.kind == "MOVE":
        return f"{e.item}  {e.src or '—'} > {e.dst}" + (f"  @{e.sha[:7]}" if e.sha else "")
    if e.kind == "ADD":
        return f"{e.item}  added at {e.dst} ({e.note})" if e.dst else f"{e.item}  added ({e.note})"
    if e.kind == "VOID":
        return f"void {e.ref[:8]}: {e.note}"
    if e.kind == "RESOLVE":
        return f"{e.item}  ⚠ resolved: {e.dst}"
    if e.kind == "SEC":
        return f"{e.item}  security {e.dst}" + (f": {e.note}" if e.note else "")
    if e.kind == "AUD":
        return (f"{e.item}  audit: here ({e.dst})" if e.dst == e.src
                else f"{e.item}  audit: logged in {e.src or '—'}, found in {e.dst}")
    if e.kind == "STATE":
        return f"{e.item}  state {e.dst}" + (f": {e.note}" if e.note else "")
    return f"location '{e.src}' renamed to '{e.dst}'"


def render_event(e: Event) -> str:
    flags = f"  [{', '.join(e.flags)}]" if e.flags else ""
    return f"{e.id[:8]}  {e.ts.astimezone():%m-%d %H:%M}  {e.actor:<10} {describe(e)}{flags}"


def render_verdict(v: Verdict) -> str:
    return "\n".join([TAG[v.kind], *(f"  {m}" for m in v.messages)])


def exit_code(outcome: service.Outcome) -> int:
    return 1 if outcome.verdict.kind == Kind.REJECT else 0


def report(outcome: service.Outcome) -> int:
    print(render_verdict(outcome.verdict))
    if outcome.event:
        print(f"  logged: {render_event(outcome.event)}")
    return exit_code(outcome)


# --- command handlers ----------------------------------------------------------

def ask_tty(prompt: str) -> bool:
    if not sys.stdin.isatty():
        return False
    return input(prompt).strip().lower() in ("y", "yes")


def do_move(ctx: service.Context, cmd: Move, yes: bool, ask: Ask) -> int:
    first = service.submit_move(ctx, cmd)
    if first.verdict.kind != Kind.CONFIRM:
        return report(first)
    print(render_verdict(first.verdict))
    if not (yes or ask("Log it anyway? [y/N] ")):
        print("Not logged.")
        return 2
    second = service.submit_move(ctx, cmd, confirmed=True)
    if second.event is None:            # state changed between the two calls: show the new verdict
        return report(second)
    print(f"OK (confirmed)\n  logged: {render_event(second.event)}")
    return 0


def do_where(ctx: service.Context, cmd: Where) -> int:
    state = service.current_state(ctx)
    item = node_id(cmd.item, state)
    if item is None:
        print(f"REJECT\n  {not_found(cmd.item, state)}")
        return 1
    if item not in state.where:
        print(f"{item}: nowhere yet")
        return 0
    *inside, location = ancestors(state, item)
    held = f" (in {' in '.join(inside)})" if inside else ""
    other = service.open_conflicts(state).get(item, ("", ""))[1]
    flag = f"  ⚠ or {other}" if other else ""
    condition = f" · {state.conditions[item]}" if item in state.conditions else ""
    print(f"{item}: {location}{held}{condition}{flag}\n"
          f"  last: {render_event(state.last_event[item])}")
    if other:
        print(f"  Two devices disagree. Settle it: fl resolve {item} <{location} or {other}>")
    return 0


def do_at(ctx: service.Context, cmd: At) -> int:
    state = service.current_state(ctx)
    target = canonical_destination(cmd.location, state)
    items = items_at(state, target)
    print("\n".join(items) if items else f"Nothing logged at '{target}'.")
    return 0


def execute(ctx: service.Context, cmd, yes: bool, ask: Ask) -> int:
    if isinstance(cmd, Move):
        return do_move(ctx, cmd, yes, ask)
    if isinstance(cmd, Where):
        return do_where(ctx, cmd)
    if isinstance(cmd, At):
        return do_at(ctx, cmd)
    if isinstance(cmd, Void):
        return report(service.submit_void(ctx, cmd))
    return report(service.submit_rename(ctx, cmd))


def do_kit(ctx: service.Context, groups: list[Group], planner) -> int:
    for group in groups:
        if group.container is not None:
            store.set_container(ctx.ledger_dir, group.prefix, group.container)
    state = service.current_state(ctx)
    planned = [p for g in groups for p in planner(g, state)]
    written = service.add_items(ctx, planned)
    for e in written:
        print(f"  {e.item}  at {e.dst}")
    print(f"OK\n  {len(written)} item(s) added.")
    return 0


STATE_NAME = re.compile(r"[a-z][a-z0-9-]{0,19}$")


def do_kind(ctx: service.Context, prefix: str, what: str, values: list[str]) -> int:
    if what == "container":
        if values not in (["yes"], ["no"]):
            print("REJECT\n  Say yes or no: `fl kind CAS container yes`.")
            return 1
        store.set_container(ctx.ledger_dir, prefix, values == ["yes"])
        print(f"OK\n  {prefix} {'holds' if values == ['yes'] else 'does not hold'} things.")
        return 0
    states = list(dict.fromkeys(v.lower() for v in values))
    bad = [s for s in states if not STATE_NAME.match(s)]
    if not states or bad:
        print("REJECT\n  States are short words, e.g. `fl kind BAT states ready depleted "
              "storage damaged`." + (f" Not a state: {', '.join(bad)}." if bad else ""))
        return 1
    store.set_kind_states(ctx.ledger_dir, prefix, states)
    print(f"OK\n  {prefix} states: {' / '.join(states)}")
    return 0


def do_state(ctx: service.Context, item: str, value: str, reason: str) -> int:
    before = service.current_state(ctx)
    outcome = service.submit_state(ctx, item, value, reason)
    if outcome.event is None:
        return report(outcome)
    e = outcome.event
    print(f"STATE {e.item} · {before.items.get(e.item, '')} · "
          f"was {before.conditions.get(e.item, '—')} → {e.dst}")
    print(f"  logged: {render_event(e)}")
    return 0


def do_audit(ctx: service.Context) -> int:
    """Read only: what today's audit still has to check, and what it found wrong. Checks are
    written from the board's audit screen, never typed."""
    state = service.current_state(ctx)
    due, wrong = service.audit_report(state, ctx.now())
    by_place: dict[str, list[str]] = {}
    for item in due:
        by_place.setdefault(location_of(state, item), []).append(item)
    print(f"Audit due today: {len(due)}")
    for place, items in sorted(by_place.items()):
        print(f"  {place}: {', '.join(items)}")
    print(f"Mismatches today: {len(wrong)}")
    for e in wrong:
        print(f"  {render_event(e)}")
    if due:
        print("Check them on the board: Audit.")
    return 0


def do_import(ctx: service.Context, path: Path) -> int:
    results = service.import_text(ctx, path.read_text(encoding="utf-8"))
    for r in results:
        if r.status != "written":
            print(f"  line {r.line_no:>4}  {r.status:<16} {r.text}")
            for m in r.messages:
                print(f"{'':>24}{m}")
    counts = {s: sum(r.status == s for r in results) for s in {r.status for r in results}}
    print("Import: " + (", ".join(f"{n} {s}" for s, n in sorted(counts.items())) or "no commands found"))
    return 0


def do_list(events: list[Event]) -> int:
    print("\n".join(render_event(e) for e in events) or "Nothing to show.")
    return 0


# --- argument parsing ----------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fl", description="Offline movement log for field kit.")
    p.add_argument("--db", type=Path, default=Path(os.environ.get("FL_DB", "field-ledger.db")))
    p.add_argument("--ledger-dir", type=Path,
                   default=Path(os.environ.get("FL_LEDGER_DIR", store.DEFAULT_LEDGER_DIR)),
                   help="the ledger's own Git repo, which holds the record (default: ./ledger)")
    p.add_argument("--actor", help="who is logging (default: the name given to `fl init`)")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="create the ledger and set your name").add_argument("name")
    sub.add_parser("kit", help="add item groups from a CSV kit file").add_argument("file", type=Path)
    add = sub.add_parser("add", help="add N more items to a group")
    add.add_argument("prefix")
    add.add_argument("count", type=int)
    add.add_argument("--at", required=True, help="starting location")
    add.add_argument("--name", help="group name (defaults to the prefix)")
    add.add_argument("--container", action="store_true",
                     help="this kind can hold other things (a case, a van, a drone)")
    kind = sub.add_parser("kind", help="'kind CAS container yes', or a kind's states: "
                                       "'kind BAT states ready depleted storage damaged'")
    kind.add_argument("prefix")
    kind.add_argument("what", choices=["container", "states"])
    kind.add_argument("value", nargs="*")
    condition = sub.add_parser("state", help="what shape an item is in, e.g. 'state BAT-12 depleted'")
    condition.add_argument("item")
    condition.add_argument("state")
    condition.add_argument("reason", nargs="*")
    move = sub.add_parser("move", help="log a movement")
    move.add_argument("item")
    move.add_argument("to", nargs="+")
    move.add_argument("--from", dest="src", default="")
    move.add_argument("--yes", action="store_true", help="answer yes to any confirmation")
    run = sub.add_parser("run", help="one command in the text grammar, e.g. 'MOVE BAT-07 > site-b'")
    run.add_argument("line")
    run.add_argument("--yes", action="store_true")
    sub.add_parser("where").add_argument("item")
    sub.add_parser("at").add_argument("location", nargs="+")
    settle = sub.add_parser("resolve", help="settle a ⚠ by confirming one of its two places")
    settle.add_argument("item")
    settle.add_argument("location", nargs="+")
    sub.add_parser("audit", help="what today's audit still has to check (read only)")
    sub.add_parser("undo", help="take back your own last command, within 10 minutes")
    people = sub.add_parser("people", help="the names phones pick from; 'people add <name>' adds one")
    people.add_argument("add", nargs="?", choices=["add"])
    people.add_argument("name", nargs="*")
    setting = sub.add_parser("set", help="change a ledger setting, e.g. 'set build_home lab'")
    setting.add_argument("key", choices=sorted(store.DEFAULT_SETTINGS))
    setting.add_argument("value", nargs="+")
    void = sub.add_parser("void", help="cancel an event (it stays in the log, marked void)")
    void.add_argument("id")
    void.add_argument("reason", nargs="+")
    rename = sub.add_parser("rename-location", help="fix a location typo everywhere")
    rename.add_argument("old")
    rename.add_argument("new")
    sub.add_parser("import", help="import commands from a text/chat export").add_argument("file", type=Path)
    sub.add_parser("merge", help="merge another ledger file into this one").add_argument("file", type=Path)
    sub.add_parser("rebuild", help="recreate the local cache from the event files")
    sub.add_parser("flags", help="every flagged event, newest first")
    log = sub.add_parser("log", help="recent events")
    log.add_argument("-n", type=int, default=20)
    return p


def to_command(args: argparse.Namespace):
    """Map argparse output onto the same Command objects the text grammar produces."""
    if args.command == "move":
        return Move(item=args.item, dst=" ".join(args.to), src=args.src)
    if args.command == "run":
        return parse(args.line)
    if args.command == "where":
        return Where(args.item)
    if args.command == "at":
        return At(" ".join(args.location))
    if args.command == "void":
        return Void(args.id, " ".join(args.reason))
    if args.command == "rename-location":
        return Rename(args.old, args.new)
    return None


def open_ledger(ledger_dir: Path, db: Path, actor: str | None,
                now: Callable[[], datetime], name: str | None = None) -> service.Context:
    """Open a ledger that already exists, cache synced to the record.

    Shared with `field-ledger` (code mode), so both commands write through the same
    path. `name` is the one set by `init`; it is stored before the actor is read.
    """
    if not (ledger_dir / ".git").exists():
        raise SystemExit(f"No ledger at {ledger_dir}. Run `fl init <your-name>` first, "
                         "or pass --ledger-dir.")
    conn = store.connect(db)
    device = store.ensure_device(conn)
    store.sync(conn, ledger_dir)
    if name:
        store.set_meta(conn, "actor", name)
    actor = actor or store.get_meta(conn, "actor")
    if not actor:
        raise SystemExit("No name set. Run `fl init <your-name>` first, or pass --actor.")
    return service.Context(conn, actor, device, now, ledger_dir)


def make_context(args: argparse.Namespace, now: Callable[[], datetime]) -> service.Context:
    if args.command == "init":
        store.init_ledger(args.ledger_dir)
    return open_ledger(args.ledger_dir, args.db, args.actor, now,
                       args.name if args.command == "init" else None)


def dispatch(ctx: service.Context, args: argparse.Namespace, ask: Ask) -> int:
    if args.command == "init":
        store.add_person(ctx.ledger_dir, ctx.actor)          # pickable on a phone too
        print(f"OK\n  ledger: {args.ledger_dir}  cache: {args.db}  device: {ctx.device}  "
              f"name: {ctx.actor}")
        return 0
    if args.command == "kit":
        return do_kit(ctx, read_kit(args.file.read_text(encoding="utf-8")), plan_kit)
    if args.command == "add":
        group = Group(args.prefix.upper(), args.name or args.prefix.upper(), args.count,
                      canonical_location(args.at), True if args.container else None)
        return do_kit(ctx, [group], plan_more)
    if args.command == "import":
        return do_import(ctx, args.file)
    if args.command == "resolve":
        return report(service.submit_resolve(ctx, args.item, " ".join(args.location)))
    if args.command == "kind":
        if not is_prefix(args.prefix):
            print(f"REJECT\n  '{args.prefix}' isn't a kind: 3 letters, e.g. CAS.")
            return 1
        return do_kind(ctx, args.prefix.upper(), args.what, args.value)
    if args.command == "state":
        return do_state(ctx, args.item, args.state, " ".join(args.reason))
    if args.command == "people":
        if args.add and args.name:
            print(f"OK\n  {store.add_person(ctx.ledger_dir, ' '.join(args.name))} is on the list.")
        for name in store.read_people(ctx.ledger_dir):
            print(f"  {name}")
        return 0
    if args.command == "set":
        value = canonical_location(" ".join(args.value))
        store.write_setting(ctx.ledger_dir, args.key, value)
        print(f"OK\n  {args.key}: {value}")
        return 0
    if args.command == "merge":
        merged = store.merge(ctx.conn, args.file)
        store.sync(ctx.conn, ctx.ledger_dir)
        print(f"OK\n  {merged} new event(s) merged.")
        return 0
    if args.command == "rebuild":
        print(f"OK\n  cache rebuilt: {store.rebuild(ctx.conn, ctx.ledger_dir)} event(s).")
        return 0
    if args.command == "undo":
        return report(service.submit_undo(ctx))
    if args.command == "audit":
        return do_audit(ctx)
    if args.command == "flags":
        return do_list(service.flagged_events(service.current_state(ctx)))
    if args.command == "log":
        return do_list(list(reversed(service.current_state(ctx).events))[:args.n])
    return execute(ctx, to_command(args), getattr(args, "yes", False), ask)


def main(argv: list[str] | None = None, ask: Ask = ask_tty,
         now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> int:
    args = build_parser().parse_args(argv)
    try:
        return dispatch(make_context(args, now), args, ask)
    except (ParseError, ValueError) as err:
        print(f"REJECT\n  {err}")
        return 1
