"""Entry point: wire the sources, classifier and renderer together.

Usage:
    python -m field_ledger init
    python -m field_ledger show feat/x --repo ~/github-repos/casio-edge
    python -m field_ledger --repo ~/github-repos/casio-edge --base origin/develop --prs gh
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .classify import build_row, sort_rows
from .git_source import is_merged, last_commit, list_branches, run_git
from .ledger import store
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


def do_show(argv: list[str], now: datetime) -> int:
    """`field-ledger show <branch>`: derived state from local Git only, so it works offline."""
    p = argparse.ArgumentParser(prog="field-ledger show",
                                description="Branch age and last commit, from local Git.")
    p.add_argument("branch")
    p.add_argument("--repo", type=Path, default=Path("."), help="path to a local clone")
    p.add_argument("--remote", default="origin")
    args = p.parse_args(argv)
    commit = last_commit(args.repo, args.branch, args.remote)
    if commit is None:
        print(f"REJECT\n  No branch '{args.branch}' in {args.repo} (local or {args.remote}/).")
        return 1
    print(render_show(args.branch, commit, now))
    return 0


def main(argv: list[str] | None = None) -> int | None:
    argv = sys.argv[1:] if argv is None else argv
    # ponytail: subcommands peeled off the front, so the flags-only board call
    # keeps working unchanged. Switch to subparsers once there are three of these.
    if argv and argv[0] == "init":
        return do_init(argv[1:])
    if argv and argv[0] == "show":
        return do_show(argv[1:], datetime.now(timezone.utc))
    args = parse_args(argv)
    print(render_table(collect(args, datetime.now(timezone.utc))))
