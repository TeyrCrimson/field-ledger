from datetime import datetime, timedelta, timezone

from field_ledger.classify import build_row, classify, days_between, sort_rows
from field_ledger.model import Branch, Label, PullRequest

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


def branch(days_old: int, name: str = "feat/x") -> Branch:
    return Branch(name=name, last_commit=NOW - timedelta(days=days_old), author="t")


def pr(days_idle: int) -> PullRequest:
    return PullRequest(branch="feat/x", number=1, updated_at=NOW - timedelta(days=days_idle), url="u")


def test_days_between_never_negative():
    assert days_between(NOW, NOW - timedelta(days=3)) == 0


def test_merged_wins_over_everything():
    assert classify(branch(30), None, merged=True, now=NOW, stale_days=7) == Label.MERGED_NOT_DELETED


def test_no_pr():
    assert classify(branch(1), None, merged=False, now=NOW, stale_days=7) == Label.NO_PR


def test_pr_stale_is_strictly_greater_than_threshold():
    assert classify(branch(1), pr(7), False, NOW, 7) == Label.IN_FLIGHT
    assert classify(branch(1), pr(8), False, NOW, 7) == Label.PR_STALE


def test_sort_puts_no_pr_first_then_oldest():
    rows = [build_row(branch(2, "a"), pr(0), False, NOW, 7),
            build_row(branch(5, "b"), None, False, NOW, 7),
            build_row(branch(20, "c"), None, False, NOW, 7)]
    assert [r.branch.name for r in sort_rows(rows)] == ["c", "b", "a"]
