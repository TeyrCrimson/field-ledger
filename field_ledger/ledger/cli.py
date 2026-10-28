"""`fl`: command-line adapter over `service`. Prints verdicts; never decides anything itself.

Exit codes: 0 written/ignored/query ok, 1 rejected, 2 confirmation declined.
"""

import argparse
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from . import service, store
from .ids import canonical_item, canonical_location, suggest
from .kit import Group, plan_kit, plan_more, read_kit
from .model import At, Event, Kind, Move, Rename, Verdict, Void, Where
from .parse import ParseError, parse
from .state import ancestors, items_at
from .validate import canonical_destination, node_id

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
        hint = suggest(canonical_item(cmd.item) or cmd.item, set(state.items))
        print(f"REJECT\n  '{cmd.item}' is not in the kit." + (f" Did you mean {hint}?" if hint else ""))
        return 1
    if item not in state.where:
        print(f"{item}: nowhere yet")
        return 0
    *inside, location = ancestors(state, item)
    held = f" (in {' in '.join(inside)})" if inside else ""
    print(f"{item}: {location}{held}\n  last: {render_event(state.last_event[item])}")
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
    state = service.current_state(ctx)
    planned = [p for g in groups for p in planner(g, state)]
    written = service.add_items(ctx, planned)
    for e in written:
        print(f"  {e.item}  at {e.dst}")
    print(f"OK\n  {len(written)} item(s) added.")
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
    sub.add_parser("undo", help="cancel your own last event, within 10 minutes")
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
        print(f"OK\n  ledger: {args.ledger_dir}  cache: {args.db}  device: {ctx.device}  "
              f"name: {ctx.actor}")
        return 0
    if args.command == "kit":
        return do_kit(ctx, read_kit(args.file.read_text(encoding="utf-8")), plan_kit)
    if args.command == "add":
        group = Group(args.prefix.upper(), args.name or args.prefix.upper(), args.count,
                      canonical_location(args.at))
        return do_kit(ctx, [group], plan_more)
    if args.command == "import":
        return do_import(ctx, args.file)
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
