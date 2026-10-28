"""Turn rows into text. Markdown so it pastes cleanly into Telegram, Notion or a PR."""

from collections import Counter
from datetime import datetime

from .classify import days_between
from .model import Commit, Row

HEADER = "| Label | Branch | Age (d) | Author | PR |\n|---|---|---|---|---|"


def render_row(row: Row) -> str:
    pr = f"[#{row.pr.number}]({row.pr.url})" if row.pr else "-"
    return f"| {row.label.value} | `{row.branch.name}` | {row.age_days} | {row.branch.author} | {pr} |"


def render_summary(rows: list[Row]) -> str:
    """One line of counts, e.g. 'no-PR: 3 · PR-stale: 1'."""
    counts = Counter(r.label.value for r in rows)
    return " · ".join(f"{label}: {n}" for label, n in counts.items()) or "nothing in flight"


def render_table(rows: list[Row]) -> str:
    body = "\n".join(render_row(r) for r in rows)
    return f"{render_summary(rows)}\n\n{HEADER}\n{body}" if rows else render_summary(rows)


def render_show(branch: str, commit: Commit, now: datetime, merged: str = "",
                deployed: str = "") -> str:
    """Everything known about one branch. `merged` and `deployed` are omitted when the
    caller could not work them out (no ref to compare, no ledger)."""
    lines = [branch,
             f"  age: {days_between(commit.when, now)} day(s) since the last commit",
             f"  last commit: {commit.sha[:7]}  {commit.when:%Y-%m-%d %H:%M}  {commit.author}  "
             f"{commit.subject}"]
    if merged:
        lines.append(f"  {merged}")
    if deployed:
        lines.append(f"  {deployed}")
    return "\n".join(lines)
