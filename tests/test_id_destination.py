"""Stage 9: an ID-shaped destination that names no item is a typo, not a new place.

The stage 4 smoke test deployed to `DRN-03` with no DRN-03 in the kit and got a location
called 'drn-03', flagged but written. `move` did the same.
"""

from field_ledger.ledger import service, store
from field_ledger.ledger.model import Kind, Move
from field_ledger.ledger.state import location_of
from ledger_helpers import make_ctx, seed


def test_move_to_a_missing_id_is_refused_and_nothing_written(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    seed(ctx)                                               # BAT-01..03, CAM-01
    before = len(service.current_state(ctx).events)
    outcome = service.submit_move(ctx, Move("BAT-01", "DRN-99"))
    assert outcome.verdict.kind == Kind.REJECT and outcome.event is None
    assert outcome.verdict.messages == ("DRN-99 is not in the kit. Add it first with `fl add`.",)
    assert len(service.current_state(ctx).events) == before


def test_a_close_item_is_suggested(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    seed(ctx)
    outcome = service.submit_move(ctx, Move("BAT-01", "CAM-02"))
    assert outcome.verdict.messages == ("CAM-02 is not in the kit. Did you mean CAM-01?",)


def test_deploy_to_a_missing_id_is_refused(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    outcome = service.submit_deploy(ctx, "feat/x", "DRN-03")
    assert outcome.verdict.kind == Kind.REJECT and outcome.event is None
    assert "feat/x" not in service.current_state(ctx).items          # no build, no hq either


def test_items_and_plain_places_still_work(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    seed(ctx)
    assert service.submit_move(ctx, Move("BAT-01", "cam-01")).event is not None    # an item
    assert service.submit_move(ctx, Move("BAT-02", "drone-3")).event is not None   # a place


def test_an_older_ledger_that_already_has_such_a_place_keeps_working(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    seed(ctx)
    old = service.make_event(ctx, "MOVE", item="BAT-01", dst="drn-03")   # written before stage 9
    store.add(ctx.conn, ctx.ledger_dir, [old])
    assert location_of(service.current_state(ctx), "BAT-01") == "drn-03"
    assert service.submit_move(ctx, Move("BAT-02", "DRN-03")).event is not None
