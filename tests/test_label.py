"""Stage 6: a build's security label (SEC), set by hand, and the drift warning in `show`.

Labels are a fixed five so the board can count and compare them. Never-labelled and NA
are different answers: nobody has looked, versus looked and it doesn't apply.
"""

import pytest

from field_ledger.cli import main
from field_ledger.ledger.state import fold
from field_ledger.ledger.store import read_events
from test_deploy import deploy, ledger, repo, show  # noqa: F401  (repo is a fixture)
from test_integration import commit, git


def label(tmp_path, *argv):
    return main(["label", *argv, "--ledger-dir", str(tmp_path / "ledger"),
                 "--db", str(tmp_path / "l.db")])


def labels(tmp_path):
    return fold(read_events(tmp_path / "ledger")).labels


@pytest.mark.parametrize("typed", ["CRIT", "high", "Med", "low", "na"])
def test_each_label_is_accepted_and_stored_uppercase(repo, tmp_path, typed):
    assert deploy(tmp_path, repo, "pending", "drn-03") == 0
    assert label(tmp_path, "pending", typed) == 0
    assert labels(tmp_path) == {"pending": typed.upper()}


def test_an_unknown_label_is_rejected_and_nothing_written(repo, tmp_path, capsys):
    assert deploy(tmp_path, repo, "pending", "drn-03") == 0
    before = len(read_events(tmp_path / "ledger"))
    assert label(tmp_path, "pending", "spicy") == 1
    assert "'SPICY' is not a security label. Use one of CRIT / HIGH / MED / LOW / NA." \
        in capsys.readouterr().out
    assert len(read_events(tmp_path / "ledger")) == before


def test_only_builds_carry_a_label(repo, tmp_path, capsys):
    assert ledger(tmp_path, "add", "BAT", "1", "--at", "van") == 0
    capsys.readouterr()
    assert label(tmp_path, "BAT-01", "LOW") == 1
    assert "BAT-01 is not a build" in capsys.readouterr().out
    assert label(tmp_path, "feat/never-deployed", "LOW") == 1
    assert "is not in the ledger" in capsys.readouterr().out


def test_readback_and_reason(repo, tmp_path, capsys):
    assert deploy(tmp_path, repo, "pending", "drn-03") == 0
    capsys.readouterr()
    assert label(tmp_path, "pending", "LOW") == 0
    assert capsys.readouterr().out.startswith("SEC pending · drn-03 · was — → LOW")
    assert label(tmp_path, "pending", "CRIT", "exposes", "the", "CDR", "port") == 0
    out = capsys.readouterr().out
    assert out.startswith("SEC pending · drn-03 · was LOW → CRIT")
    assert "pending  security CRIT: exposes the CDR port" in out
    sec = [e for e in read_events(tmp_path / "ledger") if e.kind == "SEC" and e.dst == "CRIT"]
    assert sec[0].note == "exposes the CDR port"


def test_latest_wins_and_undo_brings_the_previous_back(repo, tmp_path):
    assert deploy(tmp_path, repo, "pending", "drn-03") == 0
    assert label(tmp_path, "pending", "LOW") == 0
    assert label(tmp_path, "pending", "CRIT") == 0
    assert labels(tmp_path) == {"pending": "CRIT"}
    assert main(["undo", "--ledger-dir", str(tmp_path / "ledger"),
                 "--db", str(tmp_path / "l.db")]) == 0
    assert labels(tmp_path) == {"pending": "LOW"}


def test_show_tells_never_labelled_from_na(repo, tmp_path, capsys):
    assert deploy(tmp_path, repo, "pending", "drn-03") == 0
    capsys.readouterr()
    assert show(tmp_path, repo, "pending") == 0
    assert "security label: none set" in capsys.readouterr().out
    assert label(tmp_path, "pending", "NA") == 0
    capsys.readouterr()
    assert show(tmp_path, repo, "pending") == 0
    assert "security label: NA" in capsys.readouterr().out


# --- drift: warn only ------------------------------------------------------------

def test_show_warns_when_the_branch_moved_on_since_deploy(repo, tmp_path, capsys):
    assert deploy(tmp_path, repo, "pending", "drn-03") == 0
    deployed = capsys.readouterr().out.split("deployed as ")[1].split()[0]
    assert show(tmp_path, repo, "pending") == 0
    assert "moved on since deploy" not in capsys.readouterr().out      # nothing new yet
    git(repo, "checkout", "pending")
    commit(repo, "later work")
    git(repo, "push", "origin", "pending")
    before = len(read_events(tmp_path / "ledger"))
    assert show(tmp_path, repo, "pending") == 0
    out = capsys.readouterr().out
    assert f"moved on since deploy: deployed as {deployed}, head is now " in out
    assert len(read_events(tmp_path / "ledger")) == before            # warn only: no event


def test_no_drift_warning_when_the_commit_is_unknown(repo, tmp_path, capsys):
    assert deploy(tmp_path, repo, "feat/later", "drn-03") == 0       # not in the clone yet
    assert "commit unknown" in capsys.readouterr().out
    git(repo, "branch", "feat/later")                                # now it is
    assert show(tmp_path, repo, "feat/later") == 0
    out = capsys.readouterr().out
    assert "at drn-03, commit unknown" in out and "moved on" not in out
