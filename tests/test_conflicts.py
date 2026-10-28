"""Stage 7: the ⚠ rule (README "When two moves disagree") and RESOLVE.

Each case below is one clause of the rule. Two devices share one cache here, as two
phones' events would after a sync; only the device id differs.
"""

from dataclasses import replace
from datetime import timedelta

from field_ledger.ledger import service
from field_ledger.ledger.cli import main as fl_main
from field_ledger.ledger.kit import Group, plan_more
from field_ledger.ledger.model import Kind, Move
from field_ledger.ledger.state import conflicts
from ledger_helpers import Clock, make_ctx, seed


def two_phones(tmp_path):
    """Teyr's phone and Yoeng's phone over the same ledger. BAT-01..03 start in the truck."""
    clock = Clock()
    teyr = make_ctx(tmp_path / "l.db", "teyr", clock)
    seed(teyr)
    return teyr, replace(teyr, actor="yoeng", device="yoeng-phone"), clock


def warned(ctx):
    return service.open_conflicts(service.current_state(ctx))


def test_two_devices_two_places_inside_the_window(tmp_path):
    teyr, yoeng, clock = two_phones(tmp_path)
    service.submit_move(teyr, Move("BAT-01", "van"))
    clock.advance(minutes=4)
    service.submit_move(yoeng, Move("BAT-01", "site-b"))
    assert warned(teyr) == {"BAT-01": ("site-b", "van")}      # latest, then the other


def test_outside_the_window_latest_wins(tmp_path):
    teyr, yoeng, clock = two_phones(tmp_path)
    service.submit_move(teyr, Move("BAT-01", "van"))
    clock.advance(minutes=6)
    service.submit_move(yoeng, Move("BAT-01", "site-b"))
    assert warned(teyr) == {}


def test_same_destination_is_a_duplicate(tmp_path):
    teyr, yoeng, clock = two_phones(tmp_path)
    service.submit_move(teyr, Move("BAT-01", "van"))
    clock.advance(minutes=1)
    service.submit_move(yoeng, Move("BAT-01", "van"))
    assert warned(teyr) == {}


def test_one_device_never_conflicts_with_itself(tmp_path):
    teyr, _, clock = two_phones(tmp_path)
    service.submit_move(teyr, Move("BAT-01", "van"))
    clock.advance(minutes=1)
    service.submit_move(teyr, Move("BAT-01", "site-b"))
    assert warned(teyr) == {}


def test_an_import_gets_the_wider_window_even_from_one_device(tmp_path):
    teyr, _, clock = two_phones(tmp_path)
    service.import_text(teyr, "MOVE BAT-01 > van\n")
    clock.advance(minutes=30)
    service.submit_move(teyr, Move("BAT-01", "site-b"))
    assert warned(teyr) == {"BAT-01": ("site-b", "van")}
    clock.advance(minutes=31)
    service.import_text(teyr, "MOVE BAT-02 > van\n")
    clock.advance(minutes=61)
    service.submit_move(teyr, Move("BAT-02", "site-b"))
    assert "BAT-02" not in warned(teyr)


def test_through_a_container_either_order(tmp_path):
    """Yoeng takes BAT-01 out of CAS-01 to site-b while Teyr moves the case to the van."""
    for case_first in (True, False):
        teyr, yoeng, clock = two_phones(tmp_path / str(case_first))
        service.add_items(teyr, plan_more(Group("CAS", "Case", 1, "truck"),
                                          service.current_state(teyr)))
        service.submit_move(teyr, Move("BAT-01", "CAS-01"))
        clock.advance(minutes=30)
        first, second = ((teyr, Move("CAS-01", "van")), (yoeng, Move("BAT-01", "site-b")))
        if not case_first:
            first, second = second, first
        service.submit_move(*first)
        clock.advance(minutes=2)
        service.submit_move(*second)
        assert warned(teyr) == {"BAT-01": ("site-b", "CAS-01")}, case_first


def test_the_window_is_passed_in(tmp_path):
    teyr, yoeng, clock = two_phones(tmp_path)
    service.submit_move(teyr, Move("BAT-01", "van"))
    clock.advance(minutes=3)
    service.submit_move(yoeng, Move("BAT-01", "site-b"))
    state = service.current_state(teyr)
    assert conflicts(state, timedelta(minutes=2), timedelta(minutes=60)) == {}
    assert "BAT-01" in conflicts(state, timedelta(minutes=5), timedelta(minutes=60))


def test_a_later_move_settles_it(tmp_path):
    teyr, yoeng, clock = two_phones(tmp_path)
    service.submit_move(teyr, Move("BAT-01", "van"))
    clock.advance(minutes=1)
    service.submit_move(yoeng, Move("BAT-01", "site-b"))
    clock.advance(minutes=20)
    service.submit_move(teyr, Move("BAT-01", "store"))
    assert warned(teyr) == {}


# --- RESOLVE ---------------------------------------------------------------------

def test_resolve_clears_it_and_can_pick_the_other_place(tmp_path):
    teyr, yoeng, clock = two_phones(tmp_path)
    service.submit_move(teyr, Move("BAT-01", "van"))
    clock.advance(minutes=1)
    service.submit_move(yoeng, Move("BAT-01", "site-b"))
    clock.advance(minutes=1)
    outcome = service.submit_resolve(teyr, "bat-01", "van")
    assert outcome.event.kind == "RESOLVE" and outcome.event.dst == "van"
    state = service.current_state(teyr)
    assert service.open_conflicts(state) == {} and state.where["BAT-01"] == "van"
    service.submit_undo(teyr)                                 # undoing it brings the ⚠ back
    assert warned(teyr) == {"BAT-01": ("site-b", "van")}


def test_resolve_refuses_without_a_conflict_or_a_third_place(tmp_path):
    teyr, yoeng, clock = two_phones(tmp_path)
    assert service.submit_resolve(teyr, "BAT-01", "truck").verdict.messages == (
        "BAT-01 has no ⚠ to resolve.",)
    service.submit_move(teyr, Move("BAT-01", "van"))
    clock.advance(minutes=1)
    service.submit_move(yoeng, Move("BAT-01", "site-b"))
    refused = service.submit_resolve(teyr, "BAT-01", "store")
    assert refused.verdict.kind == Kind.REJECT and refused.event is None
    assert refused.verdict.messages == ("Pick one of site-b or van.",)


def test_where_shows_the_other_candidate_and_resolve_settles_it(tmp_path, capsys):
    db, ledger, clock = tmp_path / "l.db", tmp_path / "ledger", Clock()

    def fl(*argv):
        return fl_main(["--db", str(db), "--ledger-dir", str(ledger), *argv], now=clock)

    assert fl("init", "teyr") == 0
    assert fl("add", "BAT", "1", "--at", "truck") == 0
    teyr = replace(make_ctx(db, "teyr", clock), ledger_dir=ledger)   # the same cache as `fl`
    clock.advance(minutes=1)
    service.submit_move(teyr, Move("BAT-01", "van"))
    clock.advance(seconds=30)
    service.submit_move(replace(teyr, actor="yoeng", device="yoeng-phone"),
                        Move("BAT-01", "site-b"))
    clock.advance(minutes=1)
    capsys.readouterr()
    assert fl("where", "BAT-01") == 0
    out = capsys.readouterr().out
    assert out.startswith("BAT-01: site-b  ⚠ or van")
    assert "fl resolve BAT-01 <site-b or van>" in out
    assert fl("resolve", "BAT-01", "site-b") == 0
    assert "⚠ resolved: site-b" in capsys.readouterr().out
    assert fl("where", "BAT-01") == 0
    assert capsys.readouterr().out.startswith("BAT-01: site-b\n")     # no "⚠ or" any more
