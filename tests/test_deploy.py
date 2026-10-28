"""Stage 4: deploy, readback, the 10-minute undo, and what `show` says about both.

The clock is injected everywhere, so the undo window is tested without sleeping.
"""

import subprocess

import pytest

from field_ledger.cli import main
from field_ledger.ledger import service
from field_ledger.ledger.cli import main as fl_main
from field_ledger.ledger.kit import Group, plan_more
from field_ledger.ledger.model import Kind, Move
from field_ledger.ledger.state import fold, items_at, location_of
from field_ledger.ledger.store import read_events
from ledger_helpers import Clock, make_ctx, seed
from test_integration import commit, git, make_repo


def deploy(tmp_path, work, *argv, clock=None, ask=lambda _: False):
    """`field-ledger deploy ...` against a ledger of this test's own."""
    return main(["deploy", *argv, "--repo", str(work),
                 "--ledger-dir", str(tmp_path / "ledger"), "--db", str(tmp_path / "l.db")],
                ask=ask, now=clock or Clock())


def show(tmp_path, work, *argv, clock=None):
    return main(["show", *argv, "--repo", str(work),
                 "--ledger-dir", str(tmp_path / "ledger")], now=clock or Clock())


def ledger(tmp_path, *argv, clock=None, ask=lambda _: False):
    return fl_main(["--db", str(tmp_path / "l.db"), "--ledger-dir", str(tmp_path / "ledger"),
                    *argv], ask=ask, now=clock or Clock())


@pytest.fixture
def repo(tmp_path):
    """A throwaway clone plus an initialised ledger next to it."""
    work = make_repo(tmp_path)
    assert ledger(tmp_path, "init", "teyr") == 0
    return work


# --- deploy and the readback ---------------------------------------------------

def test_deploy_readback_shows_the_previous_location(repo, tmp_path, capsys):
    assert deploy(tmp_path, repo, "pending", "drn-03") == 0
    assert capsys.readouterr().out.startswith("✓ pending · build · was in hq → drn-03, deployed as ")
    assert deploy(tmp_path, repo, "pending", "site-b") == 0
    assert "✓ pending · build · was in drn-03 → site-b" in capsys.readouterr().out


def test_deploy_makes_a_build_node_and_logs_where_it_came_from(repo, tmp_path, capsys):
    assert deploy(tmp_path, repo, "pending", "drn-03") == 0
    assert deploy(tmp_path, repo, "pending", "site-b") == 0
    state = fold(read_events(tmp_path / "ledger"))
    assert state.items["pending"] == "build"
    first, second = [e for e in state.events if e.kind == "MOVE"]
    assert (first.src, second.src) == ("hq", "drn-03")       # a new build starts at home
    capsys.readouterr()
    assert ledger(tmp_path, "where", "pending") == 0
    assert "pending  drn-03 > site-b" in capsys.readouterr().out

def test_build_home_is_a_ledger_setting(repo, tmp_path, capsys):
    assert ledger(tmp_path, "set", "build_home", "Lab") == 0
    assert "build_home: lab" in capsys.readouterr().out
    last = subprocess.run(["git", "-C", str(tmp_path / "ledger"), "log", "-1", "--format=%s"],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert last == "set build_home = lab"                  # shared through the ledger repo
    assert deploy(tmp_path, repo, "pending", "drn-03") == 0
    assert "· build · was in lab → drn-03" in capsys.readouterr().out
    assert location_of(fold(read_events(tmp_path / "ledger")), "pending") == "drn-03"


def test_a_move_records_where_the_log_last_had_it(repo, tmp_path, capsys):
    """No --from typed: src is still the last known location, so the log never says '?'."""
    assert ledger(tmp_path, "add", "BAT", "1", "--at", "van") == 0
    assert ledger(tmp_path, "move", "BAT-01", "site-b") == 0
    assert "BAT-01  van > site-b" in capsys.readouterr().out

def test_deploy_records_the_head_commit_at_the_time(repo, tmp_path, capsys):
    assert deploy(tmp_path, repo, "pending", "drn-03") == 0
    deployed = capsys.readouterr().out.split("deployed as ")[1].split()[0]
    git(repo, "checkout", "pending")
    commit(repo, "later work")                       # the branch has moved on...
    git(repo, "push", "origin", "pending")
    assert show(tmp_path, repo, "pending") == 0
    out = capsys.readouterr().out
    assert f"at drn-03, deployed as {deployed}" in out      # ...the deployed commit has not
    assert f"last commit: {deployed}" not in out


def test_deploy_without_the_code_clone_says_commit_unknown(repo, tmp_path, capsys):
    assert deploy(tmp_path, repo, "feat/elsewhere", "drn-03") == 0
    out = capsys.readouterr().out
    assert "✓ feat/elsewhere · build · was in hq → drn-03, commit unknown" in out
    assert show(tmp_path, repo, "pending") == 0      # and the deploy is really in the ledger
    capsys.readouterr()
    assert ledger(tmp_path, "where", "feat/elsewhere") == 0
    assert capsys.readouterr().out.startswith("feat/elsewhere: drn-03")


def test_deploy_never_fetches(tmp_path, capsys):
    """The remote is gone: a deploy still reads the head commit from local refs."""
    work = make_repo(tmp_path)
    assert ledger(tmp_path, "init", "teyr") == 0
    (tmp_path / "remote.git").rename(tmp_path / "gone")
    assert deploy(tmp_path, work, "pending", "drn-03") == 0
    assert "commit unknown" not in capsys.readouterr().out


# --- locations as fixed nodes --------------------------------------------------

def test_deploy_target_becomes_a_fixed_location_node(repo, tmp_path):
    assert deploy(tmp_path, repo, "pending", "Site-B") == 0
    state = fold(read_events(tmp_path / "ledger"))
    assert state.fixed == {"hq", "site-b"} and state.items["site-b"] == "location"
    assert location_of(state, "pending") == "site-b"
    assert items_at(state, "site-b") == ["pending"]


def test_deploy_into_an_existing_fixed_location_node(repo, tmp_path, capsys):
    assert deploy(tmp_path, repo, "pending", "site-b") == 0
    capsys.readouterr()
    assert deploy(tmp_path, repo, "merged", "site-b") == 0       # the node already exists
    assert "→ site-b" in capsys.readouterr().out
    state = fold(read_events(tmp_path / "ledger"))
    assert state.fixed == {"hq", "site-b"}                      # created once, not twice
    assert items_at(state, "site-b") == ["merged", "pending"]


def test_deploy_onto_an_item_node(repo, tmp_path, capsys):
    """An item is a container (stage 2), so a build can sit on DRN-03 itself."""
    assert ledger(tmp_path, "add", "DRN", "3", "--at", "store") == 0
    capsys.readouterr()
    assert deploy(tmp_path, repo, "pending", "drn-03") == 0
    assert "→ DRN-03" in capsys.readouterr().out
    state = fold(read_events(tmp_path / "ledger"))
    assert location_of(state, "pending") == "store" and "DRN-03" not in state.fixed


def test_moving_a_fixed_node_asks_for_confirmation(repo, tmp_path, capsys):
    assert deploy(tmp_path, repo, "pending", "site-b") == 0
    capsys.readouterr()
    assert ledger(tmp_path, "move", "site-b", "van", ask=lambda _: False) == 2
    assert "fixed location" in capsys.readouterr().out
    assert ledger(tmp_path, "move", "site-b", "van", ask=lambda _: True) == 0
    capsys.readouterr()
    assert ledger(tmp_path, "where", "pending") == 0              # contents came along
    assert capsys.readouterr().out.startswith("pending: van (in site-b)")


def test_plain_string_locations_keep_working(tmp_path):
    """An older ledger logged locations as free text. Nothing re-creates them as nodes."""
    ctx = make_ctx(tmp_path / "old.db")
    seed(ctx)
    service.submit_deploy(ctx, "feat/x", "truck")
    state = service.current_state(ctx)
    assert state.fixed == {"hq"} and "truck" not in state.items   # only build_home is new
    assert location_of(state, "feat/x") == "truck"
    assert "feat/x" in items_at(state, "truck")


# --- undo ----------------------------------------------------------------------

def test_undo_inside_the_window(repo, tmp_path, capsys):
    clock = Clock()
    assert deploy(tmp_path, repo, "pending", "drn-03", clock=clock) == 0
    clock.advance(minutes=9)
    capsys.readouterr()
    assert main(["undo", "--ledger-dir", str(tmp_path / "ledger"),
                 "--db", str(tmp_path / "l.db")], now=clock) == 0
    out = capsys.readouterr().out
    assert "Took back 4 events from one command." in out      # hq, drn-03, the build, the move
    state = fold(read_events(tmp_path / "ledger"))
    assert "pending" not in state.items and state.fixed == set()


def test_undo_leaves_a_node_someone_has_used_since(repo, tmp_path, capsys):
    """Yoeng put a battery in drn-03 after my deploy made it: drn-03 stays, my move goes."""
    assert deploy(tmp_path, repo, "pending", "drn-03") == 0
    assert ledger(tmp_path, "--actor", "yoeng", "add", "BAT", "1", "--at", "van") == 0
    assert ledger(tmp_path, "--actor", "yoeng", "move", "BAT-01", "drn-03") == 0
    capsys.readouterr()
    assert main(["undo", "--ledger-dir", str(tmp_path / "ledger"),
                 "--db", str(tmp_path / "l.db")], now=Clock()) == 0
    assert "Kept drn-03: used since by someone else." in capsys.readouterr().out
    state = fold(read_events(tmp_path / "ledger"))
    assert state.fixed == {"drn-03"} and "pending" not in state.items
    assert location_of(state, "BAT-01") == "drn-03"


def test_undo_takes_back_a_whole_kit(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    seed(ctx)                                       # two kit commands: BAT x3, then CAM x1
    service.add_items(ctx, plan_more(Group("BAT", "Battery", 2, "van"), service.current_state(ctx)))
    outcome = service.submit_undo(ctx)
    assert outcome.verdict.messages == ("Took back 2 events from one command.",)
    assert sorted(service.current_state(ctx).items) == ["BAT-01", "BAT-02", "BAT-03", "CAM-01"]


def test_undo_takes_back_a_whole_import(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    seed(ctx)
    service.import_text(ctx, "MOVE BAT-01 > van\nMOVE BAT-02 > van\n")
    assert service.submit_undo(ctx).verdict.messages == ("Took back 2 events from one command.",)
    state = service.current_state(ctx)
    assert location_of(state, "BAT-01") == location_of(state, "BAT-02") == "truck"


def test_a_missing_build_is_not_called_kit(repo, tmp_path, capsys):
    """A build only exists from its first deploy; after undoing that, `where` says so."""
    assert deploy(tmp_path, repo, "pending", "drn-03") == 0
    assert main(["undo", "--ledger-dir", str(tmp_path / "ledger"),
                 "--db", str(tmp_path / "l.db")], now=Clock()) == 0
    capsys.readouterr()
    assert ledger(tmp_path, "where", "pending") == 1
    assert "'pending' is not in the ledger." in capsys.readouterr().out
    assert ledger(tmp_path, "where", "BAT-99") == 1                 # an ID: still a kit typo
    assert "BAT-99 is not in the kit." in capsys.readouterr().out

def test_undo_is_refused_after_the_window(repo, tmp_path, capsys):
    clock = Clock()
    assert deploy(tmp_path, repo, "pending", "drn-03", clock=clock) == 0
    clock.advance(minutes=11)
    capsys.readouterr()
    assert main(["undo", "--ledger-dir", str(tmp_path / "ledger"),
                 "--db", str(tmp_path / "l.db")], now=clock) == 1
    out = capsys.readouterr().out
    assert "11 minutes old" in out and "offered for 10" in out
    assert location_of(fold(read_events(tmp_path / "ledger")), "pending") == "drn-03"


def test_undo_only_touches_your_own_events(tmp_path):
    clock = Clock()
    ctx = make_ctx(tmp_path / "l.db", "teyr", clock)
    seed(ctx)
    service.submit_move(ctx, Move("BAT-01", "van"))
    ivan = service.Context(ctx.conn, "ivan", ctx.device, clock, ctx.ledger_dir)
    assert service.submit_undo(ivan).verdict.kind == Kind.REJECT
    assert service.submit_undo(ctx).event is not None
    assert location_of(service.current_state(ctx), "BAT-01") == "truck"


def test_undo_twice_walks_back_two_events(tmp_path):
    clock = Clock()
    ctx = make_ctx(tmp_path / "l.db", "teyr", clock)
    seed(ctx)
    service.submit_move(ctx, Move("BAT-01", "van"))
    service.submit_move(ctx, Move("BAT-01", "site-b"))
    assert service.submit_undo(ctx).event is not None
    assert location_of(service.current_state(ctx), "BAT-01") == "van"
    assert service.submit_undo(ctx).event is not None
    assert location_of(service.current_state(ctx), "BAT-01") == "truck"


def test_fl_undo_is_the_same_command(repo, tmp_path, capsys):
    assert ledger(tmp_path, "add", "BAT", "1", "--at", "truck") == 0
    assert ledger(tmp_path, "move", "BAT-01", "van") == 0
    capsys.readouterr()
    assert ledger(tmp_path, "undo") == 0
    assert ledger(tmp_path, "where", "BAT-01") == 0
    assert "BAT-01: truck" in capsys.readouterr().out


# --- show ----------------------------------------------------------------------

def test_show_reports_merge_state(repo, tmp_path, capsys):
    assert show(tmp_path, repo, "merged") == 0
    assert "merged into origin/main: yes" in capsys.readouterr().out
    assert show(tmp_path, repo, "pending") == 0
    assert "merged into origin/main: no" in capsys.readouterr().out


def test_show_says_nothing_about_a_branch_that_is_not_deployed(repo, tmp_path, capsys):
    assert show(tmp_path, repo, "pending") == 0
    assert " at " not in capsys.readouterr().out


def test_show_works_without_a_ledger(tmp_path, capsys):
    work = make_repo(tmp_path)
    assert main(["show", "pending", "--repo", str(work),
                 "--ledger-dir", str(tmp_path / "nothing-here")]) == 0
    assert "merged into origin/main: no" in capsys.readouterr().out
