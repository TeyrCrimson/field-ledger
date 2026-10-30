"""F4.3 config hash (Teyr, 2026-10-30): a build's config is recorded as a CFG event, a log of
what changed after deploying to the location. The hash is never typed or taken from a request:
the tool reads the files (on disk, or path@commit in the code repo) and computes the SHA-256.
The audit's half, `--check`, compares a copy of what's deployed with the record.
"""

import hashlib
import json
import urllib.error
import urllib.request

import pytest

from field_ledger.cli import main
from field_ledger.ledger import service
from field_ledger.ledger.state import fold, mismatches
from field_ledger.ledger.store import read_events
from ledger_helpers import Clock
from test_deploy import deploy, ledger, repo  # noqa: F401  (repo is a fixture)
from test_hub_writes import PHONE, board, post  # noqa: F401  (board is a fixture)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def cfg(tmp_path, work, *argv):
    return main(["cfg", *argv, "--repo", str(work), "--ledger-dir", str(tmp_path / "ledger"),
                 "--db", str(tmp_path / "l.db")], now=Clock())


def configs(tmp_path):
    return fold(read_events(tmp_path / "ledger")).configs


@pytest.fixture
def deployed(repo, tmp_path, capsys):
    """`pending` deployed to drone-3, and a config file on this laptop."""
    assert deploy(tmp_path, repo, "pending", "drone-3") == 0
    (tmp_path / "site.yaml").write_text("port: 8080\n")
    capsys.readouterr()
    return repo


def test_one_file_is_its_plain_sha256(deployed, tmp_path, capsys):
    assert cfg(tmp_path, deployed, "pending", str(tmp_path / "site.yaml"), "--reason", "first") == 0
    out = capsys.readouterr().out
    assert out.startswith(f"CFG pending · drone-3 · was — → {sha('port: 8080' + chr(10))[:8]}\n")
    e = configs(tmp_path)["pending"]
    assert (e.kind, e.dst, e.src, e.note) == ("CFG", sha("port: 8080\n"), str(tmp_path / "site.yaml"),
                                              "first")


def test_path_at_commit_is_read_from_the_repo_and_named_by_full_commit(deployed, tmp_path):
    assert cfg(tmp_path, deployed, "pending", "base@main") == 0
    e = configs(tmp_path)["pending"]
    assert e.dst == sha("base")
    name, _, commit_id = e.src.partition("@")
    assert name == "base" and len(commit_id) == 40


def test_a_chart_and_its_values_ignore_order_and_names(deployed, tmp_path):
    (tmp_path / "chart.tgz").write_bytes(b"\x1f\x8b chart")
    assert cfg(tmp_path, deployed, "pending", str(tmp_path / "chart.tgz"), str(tmp_path / "site.yaml")) == 0
    first = configs(tmp_path)["pending"].dst
    (tmp_path / "pulled-off-device.yaml").write_text("port: 8080\n")
    assert cfg(tmp_path, deployed, "pending", "--check", str(tmp_path / "pulled-off-device.yaml"),
               str(tmp_path / "chart.tgz")) == 0
    assert configs(tmp_path)["pending"].dst == first            # same bytes: a match, nothing new


def test_a_change_is_a_new_event_and_the_same_hash_is_not(deployed, tmp_path, capsys):
    assert cfg(tmp_path, deployed, "pending", str(tmp_path / "site.yaml")) == 0
    before = len(read_events(tmp_path / "ledger"))
    assert cfg(tmp_path, deployed, "pending", str(tmp_path / "site.yaml")) == 0
    assert "is already recorded" in capsys.readouterr().out
    assert len(read_events(tmp_path / "ledger")) == before
    (tmp_path / "site.yaml").write_text("port: 9090\n")
    assert cfg(tmp_path, deployed, "pending", str(tmp_path / "site.yaml")) == 0
    assert f"was {sha('port: 8080' + chr(10))[:8]} → {sha('port: 9090' + chr(10))[:8]}" in capsys.readouterr().out


def test_check_matches_or_logs_a_mismatch(deployed, tmp_path, capsys):
    assert cfg(tmp_path, deployed, "pending", str(tmp_path / "site.yaml")) == 0
    copy = tmp_path / "from-drone.yaml"
    copy.write_text("port: 8080\n")
    capsys.readouterr()
    assert cfg(tmp_path, deployed, "pending", "--check", str(copy)) == 0
    assert capsys.readouterr().out.startswith("✓ pending's config matches the record")
    copy.write_text("port: 8080\ndebug: true\n")
    assert cfg(tmp_path, deployed, "pending", "--check", str(copy)) == 0
    assert ": a mismatch" in capsys.readouterr().out
    state = fold(read_events(tmp_path / "ledger"))
    assert state.configs["pending"].flags == ("mismatch",)
    assert state.configs["pending"].dst == sha("port: 8080\ndebug: true\n")   # the log follows what was found
    assert [e.kind for e in mismatches(state, Clock()())] == ["CFG"]


@pytest.mark.parametrize("argv, message", [
    (["pending", "nope.yaml"], "No file 'nope.yaml'."),
    (["pending", "base@no-such-branch"], "No commit 'no-such-branch'"),
    (["pending", "missing.yaml@main"], "No file 'missing.yaml' at "),
    (["pending", "base@--output=/tmp/x"], "'--output=/tmp/x' is not a commit."),
    (["feat/never", "base@main"], "'feat/never' is not in the ledger."),
    (["pending", "--check", "base@main"], "No config recorded for pending yet"),
])
def test_refusals_write_nothing(deployed, tmp_path, capsys, argv, message):
    before = len(read_events(tmp_path / "ledger"))
    assert cfg(tmp_path, deployed, *argv) == 1
    assert message in capsys.readouterr().out
    assert len(read_events(tmp_path / "ledger")) == before


def test_only_builds_carry_a_config(deployed, tmp_path, capsys):
    assert ledger(tmp_path, "add", "BAT", "1", "--at", "van") == 0
    assert cfg(tmp_path, deployed, "BAT-01", "base@main") == 1
    assert "BAT-01 is not a build" in capsys.readouterr().out


def test_no_way_to_hand_it_a_hash(deployed, tmp_path):
    """The spoof rule: the CLI takes files only, the text grammar has no CFG, and the hub has
    no CFG write at all."""
    assert cfg(tmp_path, deployed, "pending", sha("anything")) == 1     # read as a file name: none
    assert ledger(tmp_path, "run", f"CFG pending {sha('anything')}") == 1


def test_the_hub_has_no_config_write_and_shows_it_read_only(tmp_path, board):
    base, ledger_dir, clock = board
    from ledger_helpers import make_ctx
    ctx = make_ctx(tmp_path / "l.db", "teyr", clock)
    service.submit_deploy(ctx, "feat/x", "drone-3")
    (tmp_path / "x.yaml").write_text("a: 1\n")
    service.submit_config(ctx, "feat/x", [str(tmp_path / "x.yaml")], tmp_path)
    request = urllib.request.Request(f"{base}/api/cfg", b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(request)
    assert refused.value.code == 404
    nodes = {n["id"]: n for n in json.loads(urllib.request.urlopen(f"{base}/state.json").read())["nodes"]}
    assert nodes["feat/x"]["config"] == {"sha256": sha("a: 1\n"), "files": str(tmp_path / "x.yaml")}


def test_show_says_the_config(deployed, tmp_path, capsys):
    from test_deploy import show
    assert show(tmp_path, deployed, "pending") == 0
    assert "config: none recorded" in capsys.readouterr().out
    assert cfg(tmp_path, deployed, "pending", "base@main") == 0
    capsys.readouterr()
    assert show(tmp_path, deployed, "pending") == 0
    assert f"config: {sha('base')[:12]} (base@" in capsys.readouterr().out


def test_undo_takes_a_config_back(deployed, tmp_path):
    assert cfg(tmp_path, deployed, "pending", "base@main") == 0
    assert main(["undo", "--ledger-dir", str(tmp_path / "ledger"), "--db", str(tmp_path / "l.db")],
                now=Clock()) == 0
    assert "pending" not in configs(tmp_path)
