"""`field-ledger show <branch>`: age and last commit from local Git, offline."""

import shutil
import subprocess
from datetime import datetime, timedelta, timezone

from field_ledger.cli import main
from field_ledger.model import Commit
from field_ledger.render import render_show
from test_integration import commit, git, make_repo


def test_show_works_with_the_remote_gone(tmp_path, capsys):
    work = make_repo(tmp_path)
    shutil.rmtree(tmp_path / "remote.git")            # no network, no remote at all
    assert main(["show", "pending", "--repo", str(work)]) == 0
    out = capsys.readouterr().out
    sha = git_out(work, "rev-parse", "--short=7", "origin/pending")
    assert out.startswith("pending\n  age: 0 day(s)")
    assert f"last commit: {sha}" in out and out.rstrip().endswith("pending")


def test_show_falls_back_to_a_local_branch(tmp_path, capsys):
    work = make_repo(tmp_path)
    git(work, "checkout", "-b", "local-only", "main")
    commit(work, "unpushed work")
    assert main(["show", "local-only", "--repo", str(work)]) == 0
    assert "unpushed work" in capsys.readouterr().out


def test_unknown_branch_is_rejected(tmp_path, capsys):
    work = make_repo(tmp_path)
    assert main(["show", "nope", "--repo", str(work)]) == 1
    assert "No branch 'nope'" in capsys.readouterr().out


def test_age_counts_whole_days():
    when = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
    c = Commit("abcdef1234", when, "teyr", "fix the thing")
    out = render_show("feat/x", c, when + timedelta(days=7, hours=3))
    assert "age: 7 day(s)" in out and "abcdef1  2026-10-20 09:00  teyr  fix the thing" in out


def git_out(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True).stdout.strip()
