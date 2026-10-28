"""Stage 8: the 10-30 board is the stale-work table plus three ledger columns.

`field-ledger` with no subcommand. Without a ledger it is exactly the old table; with
one it adds Location, Build and SEC, and a `branch-gone` row for every deployed build
whose branch has been deleted. It never writes to the ledger.
"""

import subprocess
from dataclasses import replace

from field_ledger.cli import main
from field_ledger.ledger import service
from field_ledger.ledger.cli import open_ledger
from field_ledger.render import HEADER, LEDGER_HEADER
from ledger_helpers import Clock
from test_deploy import deploy, repo  # noqa: F401  (repo is a fixture)
from test_integration import commit, git
from test_label import label


def board(tmp_path, work, *flags):
    return main(["--repo", str(work), "--ledger-dir", str(tmp_path / "ledger"), *flags],
                now=Clock())


def row(out, branch):
    return next(line for line in out.splitlines() if f"| `{branch}` |" in line)


def sha_of(work, ref):
    return subprocess.run(["git", "-C", str(work), "rev-parse", "--short=7", ref],
                          capture_output=True, text=True, check=True).stdout.strip()


def test_without_a_ledger_it_is_the_old_table(tmp_path, capsys):
    from test_integration import make_repo
    work = make_repo(tmp_path)
    assert board(tmp_path, work) is None
    out = capsys.readouterr().out
    assert HEADER in out and "Location" not in out


def test_a_deployed_labelled_build_gets_its_three_columns(repo, tmp_path, capsys):
    assert deploy(tmp_path, repo, "pending", "drone-3") == 0
    assert label(tmp_path, "pending", "HIGH") == 0
    capsys.readouterr()
    board(tmp_path, repo, "--no-fetch")
    out = capsys.readouterr().out
    assert LEDGER_HEADER in out
    assert row(out, "pending").endswith(f"| drone-3 | {sha_of(repo, 'origin/pending')} | HIGH |")
    assert row(out, "merged").endswith("|  |  |  |")             # not in the ledger: blank


def test_moved_on_since_deploy_shows_in_build(repo, tmp_path, capsys):
    assert deploy(tmp_path, repo, "pending", "drone-3") == 0
    deployed = sha_of(repo, "origin/pending")
    git(repo, "checkout", "pending")
    commit(repo, "later work")
    git(repo, "push", "origin", "pending")
    capsys.readouterr()
    board(tmp_path, repo, "--no-fetch")
    assert f"| drone-3 | {deployed} (moved on) |  |" in row(capsys.readouterr().out, "pending")


def test_a_conflict_shows_in_location(repo, tmp_path, capsys):
    clock = Clock()
    assert deploy(tmp_path, repo, "pending", "drone-3", clock=clock) == 0
    clock.advance(minutes=2)
    ctx = open_ledger(tmp_path / "ledger", tmp_path / "l.db", None, clock)
    service.submit_deploy(replace(ctx, actor="yoeng", device="yoeng-laptop"), "pending", "site-b")
    capsys.readouterr()
    board(tmp_path, repo, "--no-fetch")
    assert "| site-b ⚠ drone-3 |" in row(capsys.readouterr().out, "pending")


def test_a_deployed_build_whose_branch_is_gone_gets_a_row(repo, tmp_path, capsys):
    assert deploy(tmp_path, repo, "merged", "site-b") == 0
    assert label(tmp_path, "merged", "LOW") == 0
    git(repo, "checkout", "main")
    git(repo, "branch", "-d", "merged")
    git(repo, "push", "origin", "--delete", "merged")
    capsys.readouterr()
    board(tmp_path, repo)                                       # fetch --prune drops the ref
    out = capsys.readouterr().out
    assert row(out, "merged").startswith("| branch-gone | `merged` | - | - | - | site-b |")
    assert row(out, "merged").endswith("| LOW |")
    assert ("branch-gone: 1 (confirm with fl where, update with fl move <build> <location>)"
            in out.splitlines()[0])


def test_the_board_writes_nothing(repo, tmp_path, capsys):
    assert deploy(tmp_path, repo, "pending", "drone-3") == 0
    ledger = tmp_path / "ledger"

    def snapshot():
        files = sorted(p.name for p in (ledger / "events").iterdir())
        log = subprocess.run(["git", "-C", str(ledger), "log", "--format=%H"],
                             capture_output=True, text=True, check=True).stdout
        return files, log

    before = snapshot()
    board(tmp_path, repo, "--no-fetch")
    assert snapshot() == before
