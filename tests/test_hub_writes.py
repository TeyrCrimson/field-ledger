"""Field stage 2: the board writes through the hub, with the CLI's own rules.

Every POST names a person from the People list and a device, goes through the same service
functions as `fl`, and answers with the verdict and a readback line.
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

from field_ledger import hub
from field_ledger.ledger import service, store
from field_ledger.ledger.model import Move
from field_ledger.ledger.state import fold, location_of
from field_ledger.ledger.store import read_events
from ledger_helpers import Clock, make_ctx, seed

PHONE = {"actor": "Yoeng", "device": "phone-a1b2"}


@pytest.fixture
def board(tmp_path):
    """A seeded ledger (BAT-01..03 in the truck, CAM-01 at site-b), Yoeng on the People
    list, and a running hub. Yields (base url, ledger dir, clock)."""
    clock = Clock()
    ctx = make_ctx(tmp_path / "l.db", "teyr", clock)
    seed(ctx)
    store.add_person(ctx.ledger_dir, "Yoeng")
    server = hub.make_server(hub.Hub(ctx.ledger_dir, db=tmp_path / "hub.db", now=clock),
                             "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", ctx.ledger_dir, clock
    server.shutdown()


def post(base, command, **body):
    """(HTTP status, JSON answer). A refused move is still 200; a malformed request is 400."""
    request = urllib.request.Request(f"{base}/api/{command}", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def state(ledger):
    return fold(read_events(ledger))


def test_a_move_is_written_as_the_requests_person_and_device(board):
    base, ledger, _ = board
    status, answer = post(base, "move", item="bat-01", to="van", **PHONE)
    assert status == 200 and answer["verdict"] in ("ACCEPT", "WARN")
    assert answer["readback"] == "✓ BAT-01 · Battery · was in truck → van"
    event = next(e for e in read_events(ledger) if e.id == answer["event"])
    assert (event.actor, event.device) == ("Yoeng", "phone-a1b2")
    assert location_of(state(ledger), "BAT-01") == "van"


def test_a_refused_move_writes_nothing(board):
    base, ledger, _ = board
    before = len(read_events(ledger))
    status, answer = post(base, "move", item="BAT-99", to="van", **PHONE)
    assert status == 200 and answer["verdict"] == "REJECT" and answer["event"] is None
    assert answer["messages"] == ["BAT-99 is not in the kit. Add it first with `fl add`."]
    assert len(read_events(ledger)) == before


def test_confirm_round_trip(board):
    """The ask-once rule for ID-shaped places, from the phone: ask, then write on yes."""
    base, ledger, _ = board
    status, asked = post(base, "move", item="BAT-01", to="Blk 12", **PHONE)
    assert asked["verdict"] == "CONFIRM" and asked["event"] is None
    status, done = post(base, "move", item="BAT-01", to="Blk 12", confirmed=True, **PHONE)
    assert done["event"] and location_of(state(ledger), "BAT-01") == "blk 12"


def test_undo_takes_back_your_last_command(board):
    base, ledger, clock = board
    post(base, "move", item="BAT-01", to="van", **PHONE)
    clock.advance(minutes=5)
    status, answer = post(base, "undo", **PHONE)
    assert answer["verdict"] == "ACCEPT" and answer["readback"].startswith("Undone.")
    assert location_of(state(ledger), "BAT-01") == "truck"


def test_resolve_from_the_board(board):
    base, ledger, clock = board
    post(base, "move", item="BAT-01", to="van", **PHONE)
    clock.advance(minutes=1)
    post(base, "move", item="BAT-01", to="site-b", actor="Yoeng", device="phone-other")
    clock.advance(minutes=1)                    # a resolve comes after the moves it settles
    status, answer = post(base, "resolve", item="BAT-01", to="van", **PHONE)
    assert answer["readback"] == "⚠ settled: BAT-01 is in van"
    assert service.open_conflicts(state(ledger)) == {}


def test_add_items_without_the_cli(board):
    base, ledger, _ = board
    status, answer = post(base, "add", prefix="cas", count=2, at="Truck", name="Pelican case",
                          **PHONE)
    assert answer["readback"] == "✓ 2 added: CAS-01..CAS-02 · Pelican case · at truck"
    assert state(ledger).items["CAS-02"] == "Pelican case"


def test_label_a_build_from_the_board(tmp_path, board):
    base, ledger, clock = board
    ctx = make_ctx(tmp_path / "l.db", "teyr", clock)        # the same ledger as the hub
    service.submit_deploy(ctx, "feat/x", "drone-3", sha="0" * 40)
    status, answer = post(base, "label", build="feat/x", label="high", reason="opens a port",
                          **PHONE)
    assert answer["readback"] == "SEC feat/x · drone-3 · was — → HIGH"
    assert state(ledger).labels == {"feat/x": "HIGH"}


def test_joining_adds_a_person_once(board):
    base, ledger, _ = board
    status, answer = post(base, "people", name="  Ivan  Tan ")
    assert answer["name"] == "Ivan Tan" and answer["people"] == ["Yoeng", "Ivan Tan"]
    status, again = post(base, "people", name="ivan tan")
    assert again["name"] == "Ivan Tan" and again["people"] == ["Yoeng", "Ivan Tan"]
    assert json.loads(urllib.request.urlopen(f"{base}/state.json").read())["people"] == \
        ["Yoeng", "Ivan Tan"]


@pytest.mark.parametrize("body", [
    {"item": "BAT-01", "to": "van", "actor": "Stranger", "device": "phone-a1b2"},  # not a person
    {"item": "BAT-01", "to": "van", "actor": "Yoeng", "device": "bad device!"},
    {"item": "BAT-01", "actor": "Yoeng", "device": "phone-a1b2"},                   # no "to"
])
def test_malformed_writes_are_400_and_write_nothing(board, body):
    base, ledger, _ = board
    before = len(read_events(ledger))
    status, answer = post(base, "move", **body)
    assert status == 400 and answer["error"]
    assert len(read_events(ledger)) == before


def test_add_checks_its_numbers(board):
    base, _, _ = board
    assert post(base, "add", prefix="BATT", count=1, at="van", **PHONE)[0] == 400
    assert post(base, "add", prefix="BAT", count=0, at="van", **PHONE)[0] == 400
    assert post(base, "add", prefix="BAT", count="2", at="van", **PHONE)[0] == 400


def test_writes_from_two_phones_can_conflict(board):
    """Each browser has its own device id, so the ⚠ rule works between phones."""
    base, ledger, clock = board
    post(base, "move", item="BAT-02", to="van", actor="Yoeng", device="phone-a")
    clock.advance(minutes=1)
    post(base, "move", item="BAT-02", to="site-b", actor="Yoeng", device="phone-b")
    assert service.open_conflicts(state(ledger)) == {"BAT-02": ("site-b", "van")}


def test_fl_people_lists_and_adds(tmp_path, capsys):
    from field_ledger.ledger.cli import main as fl
    db, ledger = str(tmp_path / "l.db"), str(tmp_path / "ledger")
    assert fl(["--db", db, "--ledger-dir", ledger, "init", "teyr"]) == 0
    assert fl(["--db", db, "--ledger-dir", ledger, "people", "add", "Ivan", "Tan"]) == 0
    assert fl(["--db", db, "--ledger-dir", ledger, "people", "add", "ivan tan"]) == 0
    capsys.readouterr()
    assert fl(["--db", db, "--ledger-dir", ledger, "people"]) == 0
    assert capsys.readouterr().out == "  teyr\n  Ivan Tan\n"      # init adds its own name
