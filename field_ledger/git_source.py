"""Read branch state from a local git clone. Each function does one thing."""

import subprocess
from datetime import datetime
from pathlib import Path

from .model import Branch

SEP = "\x1f"  # unit separator: cannot appear in ref names or ISO dates
REF_FORMAT = SEP.join(["%(refname:short)", "%(committerdate:iso-strict)", "%(authorname)"])


def run_git(repo: Path, *args: str) -> str:
    """Run a git command in `repo` and return stdout. Raises on non-zero exit."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def parse_ref_line(line: str, remote: str) -> Branch | None:
    """Turn one `for-each-ref` line into a Branch. Returns None for the remote HEAD alias."""
    ref, date, author = line.split(SEP)
    if ref in (remote, f"{remote}/HEAD"):  # `origin` alone is how short-names show origin/HEAD
        return None
    return Branch(
        name=ref.removeprefix(f"{remote}/"),
        last_commit=datetime.fromisoformat(date),
        author=author,
    )


def list_branches(repo: Path, remote: str = "origin") -> list[Branch]:
    """All remote-tracking branches for `remote`, as of the last fetch."""
    out = run_git(repo, "for-each-ref", f"--format={REF_FORMAT}", f"refs/remotes/{remote}/")
    parsed = (parse_ref_line(line, remote) for line in out.splitlines() if line)
    return [b for b in parsed if b is not None]


def is_merged(repo: Path, branch: str, base: str, remote: str = "origin") -> bool:
    """True if every commit on `branch` is already reachable from `base`."""
    result = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", f"{remote}/{branch}", base],
        capture_output=True, text=True,
    )
    if result.returncode not in (0, 1):  # 0 = ancestor, 1 = not; anything else is a real error
        raise RuntimeError(result.stderr.strip())
    return result.returncode == 0
