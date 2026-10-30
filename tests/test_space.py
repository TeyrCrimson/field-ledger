"""The space (Teyr, 2026-10-29): vehicles, and the shared layout the board draws.

A vehicle is a kind marked vehicle: it holds things and parks at a location, never inside a
case or another vehicle, on the CLI and the board alike. The layout (where each location
sits, each icon's colour) is one file in the ledger repo: arrangement, not record.
"""

import json
import threading
import urllib.error
import urllib.request

import pytest

from field_ledger import hub
from field_ledger.ledger import service, store
from field_ledger.ledger.cli import main as fl
from field_ledger.ledger.kit import Group, plan_more
from field_ledger.ledger.model import Kind, Move
from field_ledger.ledger.state import fold, location_of
from field_ledger.ledger.store import read_events, run_git
from ledger_helpers import make_ctx, seed


@pytest.fixture
def ctx(tmp_path):
    """BAT-01..03 in the truck, CAM-01 at site-b, VAN-01 and VAN-02 (vehicles) at hq,
    CAS-01 (a case) in the truck."""
    ctx = make_ctx(tmp_path / "l.db")
    seed(ctx)
    for group in (Group("VAN", "Van", 2, "hq"), Group("CAS", "Case", 1, "truck")):
        service.add_items(ctx, plan_more(group, service.current_state(ctx)))
    store.set_kind(ctx.ledger_dir, "VAN", "vehicle", True)
    store.set_container(ctx.ledger_dir, "CAS", True)
    return ctx


def test_a_vehicle_holds_things_without_being_marked_a_container(ctx):
    outcome = service.submit_move(ctx, Move("BAT-01", "VAN-01"))
    assert outcome.event is not None
    assert location_of(service.current_state(ctx), "BAT-01") == "hq"     # it's in the van, at hq


def test_a_vehicle_parks_at_a_location_and_moves_its_load(ctx):
    service.submit_move(ctx, Move("BAT-01", "VAN-01"))
    assert service.submit_move(ctx, Move("VAN-01", "site-b")).event is not None
    assert location_of(service.current_state(ctx), "BAT-01") == "site-b"


@pytest.mark.parametrize("into", ["VAN-02", "CAS-01"])
def test_a_vehicle_never_rides_in_another_vehicle_or_a_case(ctx, into):
    before = len(read_events(ctx.ledger_dir))
    outcome = service.submit_move(ctx, Move("VAN-01", into))
    assert outcome.verdict.kind == Kind.REJECT
    assert outcome.verdict.messages == (f"VAN-01 is a vehicle: it parks at a location, not in {into}.",)
    assert len(read_events(ctx.ledger_dir)) == before


def test_fl_kind_marks_a_vehicle(tmp_path, capsys):
    db, ledger = str(tmp_path / "l.db"), tmp_path / "ledger"
    run = lambda *argv: fl(["--db", db, "--ledger-dir", str(ledger), *argv])   # noqa: E731
    assert run("init", "teyr") == 0
    assert run("kind", "trk", "vehicle", "yes") == 0
    assert "TRK is a vehicle: it holds things and parks at a location." in capsys.readouterr().out
    assert store.read_vehicles(ledger) == {"TRK"} and store.read_containers(ledger) == {"TRK"}


def test_the_board_sees_which_nodes_are_vehicles(ctx):
    nodes = {n["id"]: n for n in hub.board_state(ctx.ledger_dir)["nodes"]}
    assert nodes["VAN-01"]["vehicle"] and nodes["VAN-01"]["container"]
    assert not nodes["CAS-01"]["vehicle"] and not nodes["BAT-01"]["vehicle"]


# --- the layout ----------------------------------------------------------------------

@pytest.fixture
def base(ctx, tmp_path):
    server = hub.make_server(hub.Hub(ctx.ledger_dir, db=tmp_path / "hub.db"), "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def call(url, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_the_layout_is_shared_committed_and_never_an_event(ctx, base):
    events = len(read_events(ctx.ledger_dir))
    assert call(f"{base}/layout.json") == (200, {"positions": {}, "colours": {}})
    status, _ = call(f"{base}/api/layout", {"positions": {"hq": [40, 60]}, "colours": {"BAT-01": "red"}})
    assert status == 200
    call(f"{base}/api/layout", {"positions": {"truck": [200, 60]}, "colours": {"BAT-02": "blue"}})
    status, layout = call(f"{base}/layout.json")
    assert layout == {"positions": {"hq": [40, 60], "truck": [200, 60]},
                      "colours": {"BAT-01": "red", "BAT-02": "blue"}}
    call(f"{base}/api/layout", {"colours": {"BAT-01": None}})              # back to its own
    assert call(f"{base}/layout.json")[1]["colours"] == {"BAT-02": "blue"}
    assert len(read_events(ctx.ledger_dir)) == events                      # nothing replayed
    assert run_git(ctx.ledger_dir, "status", "--porcelain").strip() == ""  # committed
    assert fold(read_events(ctx.ledger_dir)).where == service.current_state(ctx).where


@pytest.mark.parametrize("body", [
    {"positions": {"hq": [1.5, 2]}},
    {"positions": {"hq": [-1, 2]}},
    {"positions": {"hq": "40,60"}},
    {"colours": {"BAT-01": "pink"}},
    {"positions": []},
])
def test_a_bad_layout_is_refused_and_nothing_is_written(ctx, base, body):
    status, answer = call(f"{base}/api/layout", body)
    assert status == 400 and "error" in answer
    assert not (ctx.ledger_dir / store.LAYOUT_FILE).exists()
