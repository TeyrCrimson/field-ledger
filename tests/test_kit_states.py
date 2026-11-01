"""F4.1 kit states (Teyr, 2026-10-30): what shape an item is in, separate from where it is.

Each kind lists its own states (`fl kind BAT states ready depleted storage damaged`); a
STATE event sets one. It's its own event type, not SEC: a security label is a fixed five on
builds, a state is the kind's own list on kit. A move never changes a state, and a state
never moves anything.
"""

import json
import urllib.request
import uuid

import pytest

from field_ledger import hub
from field_ledger.ledger import service, store
from field_ledger.ledger.cli import main as fl
from field_ledger.ledger.model import Kind, Move
from field_ledger.ledger.state import fold
from field_ledger.ledger.store import read_events
from ledger_helpers import make_ctx, seed
from test_hub_writes import PHONE, board, post  # noqa: F401  (board is a fixture)

BATTERY = ["ready", "depleted", "storage", "damaged"]


@pytest.fixture
def ctx(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    seed(ctx)                                               # BAT-01..03 in the truck, CAM-01
    store.set_kind_states(ctx.ledger_dir, "BAT", BATTERY)
    return ctx


def conditions(ctx):
    return fold(read_events(ctx.ledger_dir)).conditions


def test_a_state_is_stored_lowercase_with_its_reason(ctx):
    outcome = service.submit_state(ctx, "bat-01", "Depleted", "flew two sorties")
    assert outcome.verdict.kind == Kind.ACCEPT
    assert (outcome.event.kind, outcome.event.item, outcome.event.dst, outcome.event.note) == \
        ("STATE", "BAT-01", "depleted", "flew two sorties")
    assert conditions(ctx) == {"BAT-01": "depleted"}


@pytest.mark.parametrize("item, value, message", [
    ("BAT-01", "flat", "'flat' is not a BAT state. Use one of ready / depleted / storage / damaged."),
    ("CAM-01", "ready", "CAM has no states yet. `fl kind CAM states ready depleted` sets them."),
    ("truck", "ready", "'truck' is not in the ledger."),
    ("BAT-09", "ready", "BAT-09 is not in the kit."),
])
def test_refused_states_write_nothing(ctx, item, value, message):
    before = len(read_events(ctx.ledger_dir))
    outcome = service.submit_state(ctx, item, value)
    assert outcome.verdict.kind == Kind.REJECT and outcome.event is None
    assert outcome.verdict.messages[0].startswith(message)
    assert len(read_events(ctx.ledger_dir)) == before


def test_places_and_builds_have_no_state(ctx):
    assert service.submit_deploy(ctx, "feat/x", "drone-3").event      # drone-3: a place node
    assert service.submit_state(ctx, "feat/x", "ready").verdict.messages == (
        "feat/x is a build; it carries a security label, not kit with a state.",)
    assert service.submit_state(ctx, "drone-3", "ready").verdict.messages == (
        "drone-3 is a place, not kit with a state.",)


def test_state_and_place_are_separate(ctx):
    service.submit_state(ctx, "BAT-01", "depleted")
    service.submit_move(ctx, Move("BAT-01", "van"))
    state = fold(read_events(ctx.ledger_dir))
    assert state.conditions == {"BAT-01": "depleted"} and state.where["BAT-01"] == "van"
    assert state.last_event["BAT-01"].kind == "MOVE"     # a STATE is not where it was last seen


def test_latest_wins_and_undo_brings_the_previous_back(ctx):
    service.submit_state(ctx, "BAT-01", "ready")
    service.submit_state(ctx, "BAT-01", "damaged")
    assert conditions(ctx) == {"BAT-01": "damaged"}
    service.submit_undo(ctx)
    assert conditions(ctx) == {"BAT-01": "ready"}


def test_a_dropped_state_stays_in_the_log(ctx):
    service.submit_state(ctx, "BAT-01", "storage")
    store.set_kind_states(ctx.ledger_dir, "BAT", ["ready", "depleted"])
    assert conditions(ctx) == {"BAT-01": "storage"}       # true then; the next one uses the list
    assert service.submit_state(ctx, "BAT-02", "storage").verdict.kind == Kind.REJECT


# --- the CLI ---------------------------------------------------------------------------

@pytest.fixture
def run(tmp_path, capsys):
    db, ledger = str(tmp_path / "l.db"), str(tmp_path / "ledger")
    assert fl(["--db", db, "--ledger-dir", ledger, "init", "teyr"]) == 0
    assert fl(["--db", db, "--ledger-dir", ledger, "add", "BAT", "2", "--at", "truck",
               "--name", "Blue 6S"]) == 0
    capsys.readouterr()

    def go(*argv):
        code = fl(["--db", db, "--ledger-dir", ledger, *argv])
        return code, capsys.readouterr().out
    return go


def test_fl_kind_states_and_fl_state(run):
    assert run("kind", "bat", "states", "Ready", "depleted", "ready") == \
        (0, "OK\n  BAT states: ready / depleted\n")
    code, out = run("state", "bat-1", "depleted", "flew", "twice")
    assert code == 0 and out.startswith("STATE BAT-01 · Blue 6S · was — → depleted\n")
    assert "BAT-01  state depleted: flew twice" in out
    code, out = run("where", "BAT-01")
    assert out.startswith("BAT-01: truck · depleted\n")


def test_fl_kind_checks_what_it_is_given(run):
    assert run("kind", "BAT", "states")[0] == 1
    assert run("kind", "BAT", "states", "fully charged!")[0] == 1
    assert run("kind", "BAT", "container", "maybe")[0] == 1
    assert run("kind", "CAS", "container", "yes") == (0, "OK\n  CAS holds things.\n")
    assert run("state", "BAT-01", "ready")[0] == 1          # BAT has no states yet


# --- the board -------------------------------------------------------------------------

def test_state_json_carries_states_only_for_kinds_that_have_them(board):
    base, ledger, _ = board
    store.set_kind_states(ledger, "BAT", BATTERY)
    post(base, "state", item="BAT-01", state="depleted", **PHONE)
    nodes = {n["id"]: n for n in json.loads(urllib.request.urlopen(f"{base}/state.json").read())
             ["nodes"]}
    assert nodes["BAT-01"]["state"] == "depleted" and nodes["BAT-01"]["states"] == BATTERY
    assert nodes["BAT-02"]["state"] == ""
    assert "states" not in nodes["CAM-01"]


def test_set_a_state_from_the_board(board):
    base, ledger, _ = board
    store.set_kind_states(ledger, "BAT", BATTERY)
    status, answer = post(base, "state", item="BAT-01", state="damaged", reason="dropped", **PHONE)
    assert status == 200 and answer["readback"] == "STATE BAT-01 · Battery · was — → damaged"
    assert fold(read_events(ledger)).conditions == {"BAT-01": "damaged"}


def test_a_queued_state_the_hub_refuses_is_held(board):
    base, ledger, _ = board                                 # BAT has no states on this hub
    body = {"id": str(uuid.uuid4()), "item": "BAT-01", "state": "ready", **PHONE}
    status, answer = post(base, "state", **body, queued=True)
    assert answer["held"] is True and answer["verdict"] == "REJECT"
    assert store.needs_a_look(ledger)[0]["command"] == "state"
