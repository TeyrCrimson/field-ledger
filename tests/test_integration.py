"""End-to-end against a throwaway repo: bare 'remote' + a working clone.

Builds one branch per label we can produce without a PR provider:
    merged  -> merged-not-deleted
    pending -> no-PR
"""

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from field_ledger.cli import collect, parse_args
from field_ledger.model import Label


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def commit(cwd: Path, name: str) -> None:
    (cwd / name).write_text(name)
    git(cwd, "add", name)
    git(cwd, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", name)


def make_repo(tmp: Path) -> Path:
    remote, work = tmp / "remote.git", tmp / "work"
    git(tmp, "init", "--bare", "-b", "main", str(remote))
    git(tmp, "clone", str(remote), str(work))
    git(work, "checkout", "-b", "main")
    commit(work, "base")
    git(work, "push", "origin", "main")
    for branch, merge in [("merged", True), ("pending", False)]:
        git(work, "checkout", "-b", branch, "main")
        commit(work, branch)
        git(work, "push", "origin", branch)
        if merge:
            git(work, "checkout", "main")
            git(work, "merge", "--ff-only", branch)
            git(work, "push", "origin", "main")
    return work


def test_labels_against_real_repo(tmp_path):
    work = make_repo(tmp_path)
    args = parse_args(["--repo", str(work), "--base", "origin/main"])
    rows = collect(args, datetime.now(timezone.utc))
    labels = {r.branch.name: r.label for r in rows}
    assert labels == {"merged": Label.MERGED_NOT_DELETED, "pending": Label.NO_PR}
