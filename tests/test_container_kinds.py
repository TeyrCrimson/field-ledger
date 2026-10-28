"""Which kinds hold things (Teyr, 2026-10-28): a case, a van or a drone can; a battery can't.

A kind holds things only once someone says so: in the kit file (`container` column), with
`fl add --container`, `fl kind CAS container yes`, or the board's "+ Add items". The rule
is the same for the CLI and the board, because both go through `validate`.
"""

import pytest

from field_ledger import hub
from field_ledger.ledger import service, store
from field_ledger.ledger.cli import main as fl
from field_ledger.ledger.kit import Group, parse_group, plan_more
from field_ledger.ledger.model import Kind, Move
from field_ledger.ledger.state import location_of
from field_ledger.ledger.store import read_events
from ledger_helpers import make_ctx, seed


@pytest.fixture
def ctx(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    seed(ctx)                                               # BAT-01..03, CAM-01: no containers
    service.add_items(ctx, plan_more(Group("CAS", "Case", 1, "truck"), service.current_state(ctx)))
    return ctx


def test_an_item_of_a_kind_that_holds_nothing_is_refused(ctx):
    before = len(read_events(ctx.ledger_dir))
    outcome = service.submit_move(ctx, Move("BAT-01", "BAT-02"))
    assert outcome.verdict.kind == Kind.REJECT and outcome.event is None
    assert outcome.verdict.messages == (
        "BAT-02 can't hold things. `fl kind BAT container yes` makes its kind one.",)
    assert len(read_events(ctx.ledger_dir)) == before


def test_once_the_kind_holds_things_it_packs(ctx):
    assert service.submit_move(ctx, Move("BAT-01", "CAS-01")).verdict.kind == Kind.REJECT
    store.set_container(ctx.ledger_dir, "CAS", True)
    assert service.submit_move(ctx, Move("BAT-01", "CAS-01")).event is not None
    assert location_of(service.current_state(ctx), "BAT-01") == "truck"     # inside CAS-01


def test_places_always_hold_things_and_builds_never(ctx):
    assert service.submit_move(ctx, Move("BAT-01", "van")).event is not None      # a new place
    service.submit_deploy(ctx, "feat/x", "drone-3", sha="0" * 40)
    refused = service.submit_move(ctx, Move("BAT-02", "feat/x"))
    assert refused.verdict.kind == Kind.REJECT
    assert refused.verdict.messages == ("feat/x can't hold things.",)


def test_deploying_onto_an_item_needs_a_container_kind(ctx):
    assert service.submit_deploy(ctx, "feat/x", "CAM-01").verdict.kind == Kind.REJECT
    store.set_container(ctx.ledger_dir, "CAM", True)
    assert service.submit_deploy(ctx, "feat/x", "CAM-01").event is not None


def test_the_cli_sets_it_three_ways(tmp_path):
    db, ledger = str(tmp_path / "l.db"), tmp_path / "ledger"
    run = lambda *argv: fl(["--db", db, "--ledger-dir", str(ledger), *argv])   # noqa: E731
    assert run("init", "teyr") == 0
    assert run("add", "CAS", "1", "--at", "truck", "--container") == 0
    assert run("kind", "van", "container", "yes") == 0
    kit = tmp_path / "kit.csv"
    kit.write_text("prefix,name,count,location,container\nDRN,Drone,2,store,yes\nBAT,Battery,2,truck,\n")
    assert run("kit", str(kit)) == 0
    assert store.read_containers(ledger) == {"CAS", "VAN", "DRN"}
    assert run("kind", "drn", "container", "no") == 0
    assert store.read_containers(ledger) == {"CAS", "VAN"}
    assert run("kind", "drone", "container", "yes") == 1                      # not 3 letters


def test_a_kit_container_column_must_be_yes_or_no():
    with pytest.raises(ValueError, match="container must be yes or no"):
        parse_group({"prefix": "CAS", "count": "1", "location": "truck", "container": "maybe"})


def test_the_board_knows_which_cards_take_a_drop(ctx):
    store.set_container(ctx.ledger_dir, "CAS", True)
    nodes = {n["id"]: n for n in hub.board_state(ctx.ledger_dir)["nodes"]}
    assert nodes["CAS-01"]["container"] is True and nodes["BAT-01"]["container"] is False


def test_adding_from_the_board_can_make_a_container_kind(ctx):
    store.add_person(ctx.ledger_dir, "Yoeng")
    answer = hub.write(hub.Hub(ctx.ledger_dir, db=ctx.ledger_dir.parent / "hub.db"), "add",
                       {"prefix": "van", "count": 1, "at": "depot", "container": True,
                        "actor": "Yoeng", "device": "phone-a"})
    assert answer["verdict"] == "ACCEPT" and "VAN" in store.read_containers(ctx.ledger_dir)
