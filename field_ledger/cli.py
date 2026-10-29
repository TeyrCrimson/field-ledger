"""Entry point: wire the sources, classifier and renderer together.

Usage:
    python -m field_ledger init
    python -m field_ledger show feat/x --repo ~/github-repos/casio-edge
    python -m field_ledger deploy feat/x site-b --repo ~/github-repos/casio-edge
    python -m field_ledger label feat/x CRIT exposes the CDR port
    python -m field_ledger undo
    python -m field_ledger serve --lan
    python -m field_ledger --repo ~/github-repos/casio-edge --base origin/develop --prs gh

`deploy` and `undo` write to the same ledger as `fl`, through the same service layer.
"""

import argparse
import os
import sys
from dataclasses import replace
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from . import hub, qr, tls
from .classify import build_row, days_between, sort_rows
from .git_source import is_merged, last_commit, list_branches, run_git
from .ledger import service, store
from .ledger.cli import Ask, ask_tty, open_ledger, render_event, render_verdict, report
from .ledger.model import Event, Kind
from .ledger.state import State, deployed_sha, fold, location_of
from .model import Branch, Label, Row
from .pr_source import fetch_prs
from .render import render_show, render_table


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="field-ledger", description="Stale-work board for a git repo.")
    p.add_argument("--repo", type=Path, default=Path("."), help="path to a local clone")
    p.add_argument("--base", default="origin/main", help="branch that counts as 'delivered'")
    p.add_argument("--remote", default="origin")
    p.add_argument("--stale-days", type=int, default=7, help="PR idle threshold")
    p.add_argument("--prs", choices=["gh", "glab", "none"], default="none",
                   help="where to look up open PRs/MRs")
    p.add_argument("--no-fetch", action="store_true", help="skip `git fetch --prune` first")
    p.add_argument("--hide-in-flight", action="store_true", help="only show problems")
    p.add_argument("--ledger-dir", type=Path,
                   default=Path(os.environ.get("FL_LEDGER_DIR", store.DEFAULT_LEDGER_DIR)),
                   help="adds Location, Build and SEC columns when a ledger is there")
    return p.parse_args(argv)


def collect(args: argparse.Namespace, now: datetime) -> list:
    """Gather branches + PRs and label every branch except the base itself."""
    if not args.no_fetch:
        run_git(args.repo, "fetch", "--prune", args.remote)
    base_name = args.base.removeprefix(f"{args.remote}/")
    prs = fetch_prs(args.repo, args.prs)
    rows = [
        build_row(b, prs.get(b.name), is_merged(args.repo, b.name, args.base, args.remote),
                  now, args.stale_days)
        for b in list_branches(args.repo, args.remote)
        if b.name != base_name
    ]
    if args.hide_in_flight:
        rows = [r for r in rows if r.label != Label.IN_FLIGHT]
    return sort_rows(rows)


def do_init(argv: list[str]) -> None:
    """`field-ledger init`: create the ledger's own repo, outside this public one."""
    p = argparse.ArgumentParser(prog="field-ledger init",
                                description="Create the ledger's own Git repo.")
    p.add_argument("--ledger-dir", type=Path, default=store.DEFAULT_LEDGER_DIR,
                   help="where the ledger repo lives (default: ./ledger, gitignored)")
    args = p.parse_args(argv)
    created = store.init_ledger(args.ledger_dir)
    print(f"OK\n  ledger: {args.ledger_dir}  ({'created' if created else 'already there'})")


def ledger_cells(state: State, open_: dict[str, tuple[str, str]], name: str, head: str) -> dict:
    """The board's three ledger columns for one build: where it is (with a ⚠ and the other
    place), the commit deployed there (and whether the branch has moved on), its label."""
    if name not in state.where:
        return {"sec": state.labels.get(name, "")}
    sha = deployed_sha(state, name)
    build = sha[:7] if sha else "unknown"
    if sha and head and head != sha:
        build += " (moved on)"
    location = location_of(state, name)
    if name in open_:
        location += f" ⚠ {open_[name][1]}"
    return {"location": location, "build": build, "sec": state.labels.get(name, "")}


def with_ledger(rows: list[Row], args: argparse.Namespace, now: datetime) -> list[Row] | None:
    """The 10-30 board: the stale-work rows plus what the ledger knows about each build.

    Builds the ledger has deployed whose branch is gone (merged and deleted) get a row of
    their own, `branch-gone`, so someone confirms where they really are. A deployed base
    branch (a site running main) gets a `base` row: the stale-work table never lists the
    base, but the board is about what's deployed where. Read-only: the
    event files are read directly, no cache, nothing written. None when there's no ledger.
    """
    if not store.events_dir(args.ledger_dir).exists():
        return None
    state = fold(store.read_events(args.ledger_dir))
    open_ = service.open_conflicts(state)
    base_name = args.base.removeprefix(f"{args.remote}/")
    listed = {r.branch.name for r in rows} | {base_name}
    base_head = last_commit(args.repo, base_name, args.remote)
    base = ([Row(Branch(base_name, base_head.when, base_head.author), None, Label.BASE,
                 days_between(base_head.when, now))]
            if state.items.get(base_name) == "build" and base_head else [])
    gone = [Row(Branch(name, now, "-"), None, Label.BRANCH_GONE, None)   # nothing to date
            for name, kind in sorted(state.items.items())
            if kind == "build" and name not in listed
            and last_commit(args.repo, name, args.remote) is None]
    out = []
    for row in rows + gone + base:
        name = row.branch.name
        if name not in state.items:
            out.append(row)
            continue
        head = last_commit(args.repo, name, args.remote)
        out.append(replace(row, **ledger_cells(state, open_, name, head.sha if head else "")))
    return sort_rows(out)


def ledger_args(p: argparse.ArgumentParser) -> None:
    """The ledger flags, spelled the same way `fl` spells them."""
    p.add_argument("--ledger-dir", type=Path,
                   default=Path(os.environ.get("FL_LEDGER_DIR", store.DEFAULT_LEDGER_DIR)))
    p.add_argument("--db", type=Path, default=Path(os.environ.get("FL_DB", "field-ledger.db")))
    p.add_argument("--actor", help="who is logging (default: the name given to `init`)")


def merged_line(repo: Path, branch: str, base: str, remote: str) -> str:
    """Whether `base` already contains the branch. Local-only branches have no
    remote-tracking ref to compare, and `is_merged` says so by raising."""
    try:
        return f"merged into {base}: {'yes' if is_merged(repo, branch, base, remote) else 'no'}"
    except RuntimeError:
        return f"merged into {base}: unknown (nothing to compare)"


def ledger_lines(ledger_dir: Path, branch: str, head: str) -> list[str]:
    """What the ledger says about the branch: where it is, the commit deployed there,
    whether the branch has moved on since (warn only: nothing is written), its label.

    Reads the event files, not the cache: `show` is read-only and needs no device,
    no name and no ledger at all.
    """
    if not store.events_dir(ledger_dir).exists():
        return []
    state = fold(store.read_events(ledger_dir))
    if branch not in state.items:
        return []
    lines = []
    if branch in state.where:
        sha = deployed_sha(state, branch)
        lines.append(f"at {location_of(state, branch)}, "
                     + (f"deployed as {sha[:7]}" if sha else "commit unknown"))
        if sha and head != sha:
            lines.append(f"moved on since deploy: deployed as {sha[:7]}, head is now {head[:7]}")
    lines.append(f"security label: {state.labels.get(branch, 'none set')}")
    return lines


def do_show(argv: list[str], now: datetime) -> int:
    """`field-ledger show <branch>`: derived state from local Git only, so it works offline."""
    p = argparse.ArgumentParser(prog="field-ledger show",
                                description="Branch age, last commit, merge state, deployment.")
    p.add_argument("branch")
    p.add_argument("--repo", type=Path, default=Path("."), help="path to a local clone")
    p.add_argument("--remote", default="origin")
    p.add_argument("--base", default="origin/main", help="branch that counts as 'delivered'")
    p.add_argument("--ledger-dir", type=Path,
                   default=Path(os.environ.get("FL_LEDGER_DIR", store.DEFAULT_LEDGER_DIR)))
    args = p.parse_args(argv)
    commit = last_commit(args.repo, args.branch, args.remote)
    if commit is None:
        print(f"REJECT\n  No branch '{args.branch}' in {args.repo} (local or {args.remote}/).")
        return 1
    print(render_show(args.branch, commit, now,
                      merged_line(args.repo, args.branch, args.base, args.remote),
                      ledger_lines(args.ledger_dir, args.branch, commit.sha)))
    return 0


def readback(e: Event, before: str) -> str:
    """Echo the deploy back, so a wrong branch name is obvious while it is still cheap
    to fix: README, 'Logging a move'."""
    sha = f"deployed as {e.sha[:7]}" if e.sha else "commit unknown"
    return f"✓ {e.item} · build · was in {before or e.src} → {e.dst}, {sha}"


def do_deploy(argv: list[str], now: Callable[[], datetime], ask: Ask) -> int:
    """`field-ledger deploy <branch> <location>`: the branch becomes a node whose parent
    is where it is deployed. The head commit is read from the local clone; it never fetches."""
    p = argparse.ArgumentParser(prog="field-ledger deploy",
                                description="Record where a branch is deployed.")
    p.add_argument("branch")
    p.add_argument("to", nargs="+", help="a location, or an item ID to deploy onto")
    p.add_argument("--repo", type=Path, default=Path("."), help="path to a local clone")
    p.add_argument("--remote", default="origin")
    p.add_argument("--yes", action="store_true", help="answer yes to any confirmation")
    ledger_args(p)
    args = p.parse_args(argv)
    ctx = open_ledger(args.ledger_dir, args.db, args.actor, now)
    commit = last_commit(args.repo, args.branch, args.remote)
    dst, before = " ".join(args.to), service.deployed_at(ctx, args.branch)
    outcome = service.submit_deploy(ctx, args.branch, dst, commit.sha if commit else "")
    if outcome.verdict.kind == Kind.CONFIRM:
        print(render_verdict(outcome.verdict))
        if not (args.yes or ask("Log it anyway? [y/N] ")):
            print("Not logged.")
            return 2
        outcome = service.submit_deploy(ctx, args.branch, dst, commit.sha if commit else "",
                                        confirmed=True)
    if outcome.event is None:
        return report(outcome)
    print(readback(outcome.event, before))
    for message in outcome.verdict.messages:
        print(f"  {message}")
    print(f"  logged: {render_event(outcome.event)}")
    return 0


def do_label(argv: list[str], now: Callable[[], datetime]) -> int:
    """`field-ledger label <branch> <label> [reason]`: a build's security label, by hand."""
    p = argparse.ArgumentParser(prog="field-ledger label",
                                description="Set a build's security label: CRIT, HIGH, MED, LOW or NA.")
    p.add_argument("branch")
    p.add_argument("label")
    p.add_argument("reason", nargs="*", help="optional: why, kept on the event")
    ledger_args(p)
    args = p.parse_args(argv)
    ctx = open_ledger(args.ledger_dir, args.db, args.actor, now)
    before = service.current_state(ctx)
    outcome = service.submit_label(ctx, args.branch, args.label, " ".join(args.reason))
    if outcome.event is None:
        return report(outcome)
    e = outcome.event
    print(f"SEC {e.item} · {location_of(before, e.item) or '—'} · "
          f"was {before.labels.get(e.item, '—')} → {e.dst}")
    print(f"  logged: {render_event(e)}")
    return 0


def start_https(the_hub, address: str):
    """HTTPS for phones, on the same port: the hub's CA (made once) signs a certificate for
    the address it has now. Without openssl the board still works, just not offline."""
    if not tls.available():
        print("  HTTPS off: `openssl` isn't installed. Phones can use the board, but it won't "
              "open without the hub (README, \"Phones offline\").")
        return None
    folder = tls.ca_dir()
    if tls.ensure_ca(folder):
        print(f"  Made this hub's certificate authority in {folder} (keep it off the ledger repo).")
    tls.issue(folder, [address, "127.0.0.1"])
    the_hub.ca_cert, the_hub.ca_name = folder / "ca.crt", tls.ca_name(folder)
    print(f"  HTTPS on the same port, as \"{the_hub.ca_name}\".")
    return tls.context(folder)


def do_serve(argv: list[str]) -> int:
    """`field-ledger serve`: the hub. The board reads from it and writes through it."""
    p = argparse.ArgumentParser(prog="field-ledger serve",
                                description="Serve the board to this laptop, or with --lan to "
                                            "phones on the field network.")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--lan", action="store_true",
                   help="listen on every interface, not just this laptop (no logins: opt in)")
    p.add_argument("--web-dir", type=Path, default=hub.WEB_DIR,
                   help="serve another front end, e.g. a design to try")
    ledger_args(p)
    args = p.parse_args(argv)
    if not store.events_dir(args.ledger_dir).exists():
        print(f"REJECT\n  No ledger at {args.ledger_dir}. Run `fl init <your-name>` first.")
        return 1
    the_hub = hub.Hub(args.ledger_dir, args.web_dir, args.db)
    server = hub.make_server(the_hub, "0.0.0.0" if args.lan else "127.0.0.1", args.port)
    port = server.server_address[1]
    print(f"Board: http://127.0.0.1:{port}/")
    if args.lan:
        address = hub.lan_address()
        the_hub.setup_url = f"http://{address}:{port}/setup.html"
        print(f"Phones: http://{address}:{port}/")
        if hub.behind_wsl_nat(address):
            print("  WSL2 is in NAT mode: phones can't reach this address. "
                  "See README, \"The hub\", for the one-time setup.")
        server.tls = start_https(the_hub, address)
        print("Add a phone: scan this with its camera (or \"Add a phone\" on the board).")
        print(qr.terminal(qr.encode(the_hub.setup_url)))
    if not store.read_people(args.ledger_dir):
        print("  No People yet: the first person to open the board adds their name.")
    print("Ctrl-C stops it.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def do_undo(argv: list[str], now: Callable[[], datetime]) -> int:
    """`field-ledger undo`: take back your own last command, inside the undo window."""
    p = argparse.ArgumentParser(prog="field-ledger undo",
                                description="Take back your own last command, within 10 minutes.")
    ledger_args(p)
    args = p.parse_args(argv)
    return report(service.submit_undo(open_ledger(args.ledger_dir, args.db, args.actor, now)))


def main(argv: list[str] | None = None, ask: Ask = ask_tty,
         now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> int | None:
    argv = sys.argv[1:] if argv is None else argv
    # ponytail: subcommands peeled off the front, so the flags-only board call
    # keeps working unchanged. Switch to subparsers once the board moves too.
    if argv and argv[0] == "init":
        return do_init(argv[1:])
    if argv and argv[0] == "show":
        return do_show(argv[1:], now())
    if argv and argv[0] == "deploy":
        return do_deploy(argv[1:], now, ask)
    if argv and argv[0] == "label":
        return do_label(argv[1:], now)
    if argv and argv[0] == "serve":
        return do_serve(argv[1:])
    if argv and argv[0] == "undo":
        return do_undo(argv[1:], now)
    args = parse_args(argv)
    rows = collect(args, now())
    board = with_ledger(rows, args, now())
    print(render_table(rows) if board is None else render_table(board, ledger=True))
