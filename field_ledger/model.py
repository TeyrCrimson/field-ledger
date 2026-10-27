"""Plain data types shared by every module. No logic lives here."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Label(str, Enum):
    """What state a branch is in, from the shadow-board point of view."""

    MERGED_NOT_DELETED = "merged-not-deleted"  # tool is back, but the outline still shows it out
    NO_PR = "no-PR"                            # checked out, nobody knows
    PR_STALE = "PR-stale"                      # checked out, known, not moving
    IN_FLIGHT = "in-flight"                    # checked out, known, moving


@dataclass(frozen=True)
class Branch:
    name: str               # short name without the remote prefix, e.g. "feat/x"
    last_commit: datetime   # timezone-aware
    author: str


@dataclass(frozen=True)
class Commit:
    sha: str
    when: datetime          # committer date, timezone-aware
    author: str
    subject: str


@dataclass(frozen=True)
class PullRequest:
    branch: str             # head/source branch name
    number: int
    updated_at: datetime    # timezone-aware
    url: str


@dataclass(frozen=True)
class Row:
    branch: Branch
    pr: PullRequest | None
    label: Label
    age_days: int           # days since last commit on the branch
