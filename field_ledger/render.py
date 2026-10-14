"""Turn rows into text. Markdown so it pastes cleanly into Telegram, Notion or a PR."""

from collections import Counter

from .model import Row

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
