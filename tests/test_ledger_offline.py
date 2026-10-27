"""The offline contingency: bulk import from text, and merging ledgers between laptops."""

from field_ledger.ledger import service, store
from field_ledger.ledger.importer import extract_commands, repeats
from field_ledger.ledger.kit import Group, plan_more
from field_ledger.ledger.model import Move
from ledger_helpers import Clock, make_ctx, seed

CHAT = """\
[17/10/26, 13:05] Teyr: MOVE BAT-01 > site-B
[17/10/26, 13:06] Yoeng: we should move the truck later
[17/10/26, 13:07] Teyr: MOVE BAT-02 truck > site-B
[17/10/26, 13:09] Teyr: MOVE BAT-99 > site-B
[17/10/26, 13:10] Teyr: MOVE BAT-01 > site-B
"""


def statuses(results):
    return [r.status for r in results]


def test_import_picks_up_commands_and_skips_chatter(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    seed(ctx)
    results = service.import_text(ctx, CHAT)
    assert [r.line_no for r in results] == [1, 3, 4, 5]          # line 2 ignored
    # line 5 repeats line 1 with nothing in between: a duplicate report, not a new move
    assert statuses(results) == ["written", "written", "rejected", "ignored"]


def test_import_is_idempotent_even_after_time_passes(tmp_path):
    ctx = make_ctx(tmp_path / "l.db", clock=Clock())
    seed(ctx)
    service.import_text(ctx, CHAT)
    before = len(store.load(ctx.conn))
    ctx.now.advance(hours=2)                                   # outside the double-tap window
    again = service.import_text(ctx, CHAT)
    assert len(store.load(ctx.conn)) == before
    assert statuses(again) == ["already-imported", "already-imported", "rejected", "ignored"]


def test_reimport_on_a_fresh_cache_adds_nothing(tmp_path):
    """A second laptop (or a deleted cache) has only the event files. The repeated line
    must still be recognised as a repeat, not logged as a same-place move."""
    ctx = make_ctx(tmp_path / "l.db", clock=Clock())
    seed(ctx)
    service.import_text(ctx, CHAT)
    before = len(store.read_events(ctx.ledger_dir))
    (tmp_path / "l.db").unlink()
    fresh = make_ctx(tmp_path / "l.db", clock=Clock())
    fresh.now.advance(hours=2)
    again = service.import_text(fresh, CHAT)
    assert len(store.read_events(fresh.ledger_dir)) == before
    assert statuses(again) == ["already-imported", "already-imported", "rejected", "ignored"]


def test_moving_back_is_not_a_repeat():
    lines = extract_commands("MOVE BAT-01 > site-B\nMOVE BAT-01 > truck\nMOVE BAT-01 > Site-B\n"
                             "MOVE BAT-02 > van\nMOVE bat2 > VAN\n")
    assert repeats(lines) == {5: 4}


def test_rejected_import_line_succeeds_after_item_is_added(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    seed(ctx)
    service.import_text(ctx, "MOVE BAT-04 > site-B")
    service.add_items(ctx, plan_more(Group("BAT", "Battery", 1, "truck"), service.current_state(ctx)))
    [line] = service.import_text(ctx, "MOVE BAT-04 > site-B")
    assert line.status == "written"


def test_import_marks_unconfirmed_suspicious_lines(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    seed(ctx)
    [line] = service.import_text(ctx, "MOVE BAT-01 > truck")       # same place: would normally ask
    event = store.load(ctx.conn)[-1]
    assert line.status == "flagged"
    assert {"same-place", "unconfirmed-import"} <= set(event.flags)


def test_merge_combines_two_laptops_and_is_idempotent(tmp_path):
    a = make_ctx(tmp_path / "a.db", "teyr", Clock())
    seed(a)
    b_path = tmp_path / "b.db"
    b_path.write_bytes((tmp_path / "a.db").read_bytes())          # laptop B starts from a copy
    b = make_ctx(b_path, "yoeng", Clock())
    store.set_meta(b.conn, "device", "laptopb")
    b.device = "laptopb"
    b.now.advance(minutes=5)
    service.submit_move(b, Move("BAT-03", "site-b"))
    service.submit_move(a, Move("BAT-01", "site-b"))

    assert store.merge(a.conn, b_path) == 1
    assert store.merge(a.conn, b_path) == 0
    where = service.current_state(a).where
    assert where["BAT-01"] == where["BAT-03"] == "site-b"
