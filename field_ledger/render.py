"""Turn rows into text. Markdown so it pastes cleanly into Telegram, Notion or a PR."""

from collections import Counter
from datetime import datetime

from .classify import days_between
from .model import Commit, Label, Row

HEADER = "| Label | Branch | Age (d) | Author | PR |\n|---|---|---|---|---|"
LEDGER_HEADER = ("| Label | Branch | Age (d) | Author | PR | Location | Build | SEC |\n"
                 "|---|---|---|---|---|---|---|---|")
HINTS = {Label.BRANCH_GONE.value: "confirm with fl where, update with fl move <build> <location>"}


def render_row(row: Row, ledger: bool = False) -> str:
    pr = f"[#{row.pr.number}]({row.pr.url})" if row.pr else "-"
    age = "-" if row.age_days is None else row.age_days
    cells = f"| {row.label.value} | `{row.branch.name}` | {age} | {row.branch.author} | {pr} |"
    return cells + (f" {row.location} | {row.build} | {row.sec} |" if ledger else "")


def render_summary(rows: list[Row]) -> str:
    """One line of counts, e.g. 'no-PR: 3 · PR-stale: 1', with what to do where it isn't obvious."""
    counts = Counter(r.label.value for r in rows)
    return " · ".join(f"{label}: {n}" + (f" ({HINTS[label]})" if label in HINTS else "")
                      for label, n in counts.items()) or "nothing in flight"


def render_table(rows: list[Row], ledger: bool = False) -> str:
    """`ledger`: add the Location, Build and SEC columns. Without a ledger the table is
    exactly the stale-work board it always was."""
    body = "\n".join(render_row(r, ledger) for r in rows)
    header = LEDGER_HEADER if ledger else HEADER
    return f"{render_summary(rows)}\n\n{header}\n{body}" if rows else render_summary(rows)


def render_show(branch: str, commit: Commit, now: datetime, merged: str = "",
                ledger: list[str] | None = None) -> str:
    """Everything known about one branch. `merged` and the `ledger` lines are omitted when
    the caller could not work them out (no ref to compare, no ledger)."""
    lines = [branch,
             f"  age: {days_between(commit.when, now)} day(s) since the last commit",
             f"  last commit: {commit.sha[:7]}  {commit.when:%Y-%m-%d %H:%M}  {commit.author}  "
             f"{commit.subject}"]
    if merged:
        lines.append(f"  {merged}")
    lines += [f"  {line}" for line in ledger or []]
    return "\n".join(lines)
