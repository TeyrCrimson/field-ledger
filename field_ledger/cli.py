"""Entry point: wire the sources, classifier and renderer together.

Usage:
    python -m field_ledger --repo ~/github-repos/casio-edge --base origin/develop --prs gh
"""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from .classify import build_row, sort_rows
from .git_source import is_merged, list_branches, run_git
from .model import Label
from .pr_source import fetch_prs
from .render import render_table


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


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    print(render_table(collect(args, datetime.now(timezone.utc))))
