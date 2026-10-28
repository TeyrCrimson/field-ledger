"""Entry point: wire the sources, classifier and renderer together.

Usage:
    python -m field_ledger init
    python -m field_ledger show feat/x --repo ~/github-repos/casio-edge
    python -m field_ledger deploy feat/x site-b --repo ~/github-repos/casio-edge
    python -m field_ledger label feat/x CRIT exposes the CDR port
    python -m field_ledger undo
    python -m field_ledger --repo ~/github-repos/casio-edge --base origin/develop --prs gh

`deploy` and `undo` write to the same ledger as `fl`, through the same service layer.
"""

import argparse
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .classify import build_row, sort_rows
from .git_source import is_merged, last_commit, list_branches, run_git
from .ledger import service, store
from .ledger.cli import Ask, ask_tty, open_ledger, render_event, render_verdict, report
from .ledger.model import Event, Kind
from .ledger.state import fold, location_of
from .model import Label
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
        sha = state.last_event[branch].sha
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
    if argv and argv[0] == "undo":
        return do_undo(argv[1:], now)
    args = parse_args(argv)
    print(render_table(collect(args, now())))
