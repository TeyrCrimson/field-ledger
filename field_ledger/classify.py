"""Decide each branch's label. Pure functions only: no git, no network, no clock."""

from datetime import datetime

from .model import Branch, Label, PullRequest, Row

ORDER = [Label.NO_PR, Label.PR_STALE, Label.MERGED_NOT_DELETED, Label.IN_FLIGHT]


def days_between(earlier: datetime, later: datetime) -> int:
    """Whole days from `earlier` to `later`, never negative."""
    return max(0, (later - earlier).days)


def classify(branch: Branch, pr: PullRequest | None, merged: bool,
             now: datetime, stale_days: int) -> Label:
    """Rules, in priority order:
    1. merged into base           -> merged-not-deleted (the branch should be gone)
    2. no open PR                 -> no-PR
    3. PR untouched > stale_days  -> PR-stale
    4. otherwise                  -> in-flight
    """
    if merged:
        return Label.MERGED_NOT_DELETED
    if pr is None:
        return Label.NO_PR
    if days_between(pr.updated_at, now) > stale_days:
        return Label.PR_STALE
    return Label.IN_FLIGHT


def build_row(branch: Branch, pr: PullRequest | None, merged: bool,
              now: datetime, stale_days: int) -> Row:
    label = classify(branch, pr, merged, now, stale_days)
    return Row(branch=branch, pr=pr, label=label,
               age_days=days_between(branch.last_commit, now))


def sort_rows(rows: list[Row]) -> list[Row]:
    """Worst first: by label severity, then oldest first."""
    return sorted(rows, key=lambda r: (ORDER.index(r.label), -r.age_days))
