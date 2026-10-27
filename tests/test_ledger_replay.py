"""Replay: contents follow their container, cycles are refused, latest wins, and the
event files (not the SQLite cache) are the record."""

import random
from datetime import datetime, timedelta, timezone

from field_ledger.git_source import run_git
from field_ledger.ledger import service, store
from field_ledger.ledger.kit import Group, plan_more
from field_ledger.ledger.model import Event, Kind, Move
from field_ledger.ledger.state import ancestors, fold, items_at, location_of
from ledger_helpers import make_ctx, seed

T = datetime(2026, 10, 17, tzinfo=timezone.utc)


def with_case(ctx):
    """seed() plus CAS-01 in the truck, with BAT-01 packed into it."""
    seed(ctx)
    service.add_items(ctx, plan_more(Group("CAS", "Case", 1, "truck"), service.current_state(ctx)))
    assert service.submit_move(ctx, Move("BAT-01", "CAS-01")).event is not None


def ev(eid, ts, device, seq, item, dst, kind="MOVE"):
    return Event(eid, ts, device, seq, "t", kind, item=item, dst=dst)


# --- contents follow container ---------------------------------------------------

def test_moving_a_container_moves_its_contents(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    with_case(ctx)
    service.submit_move(ctx, Move("CAS-01", "van"))
    state = service.current_state(ctx)
    assert ancestors(state, "BAT-01") == ["CAS-01", "van"]
    assert location_of(state, "BAT-01") == "van"
    assert items_at(state, "van") == ["BAT-01", "CAS-01"]
    assert items_at(state, "CAS-01") == ["BAT-01"]
    assert "BAT-01" not in items_at(state, "truck")


def test_unpacked_item_stays_behind(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    with_case(ctx)
    service.submit_move(ctx, Move("BAT-01", "dock"))
    service.submit_move(ctx, Move("CAS-01", "van"))
    assert location_of(service.current_state(ctx), "BAT-01") == "dock"


def test_origin_can_name_any_level(tmp_path):
    """BAT-01 is in CAS-01 in the truck: 'from truck' is true, not a mismatch."""
    ctx = make_ctx(tmp_path / "l.db")
    with_case(ctx)
    out = service.submit_move(ctx, Move("BAT-01", "site-b", src="truck"))
    assert "from-mismatch" not in out.event.flags


# --- cycles ----------------------------------------------------------------------

def test_cycle_is_rejected_and_writes_nothing(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    with_case(ctx)
    before = len(store.read_events(ctx.ledger_dir))
    for dst in ("BAT-01", "CAS-01"):              # into its own content; into itself
        out = service.submit_move(ctx, Move("CAS-01", dst))
        assert out.verdict.kind == Kind.REJECT and out.event is None
    assert len(store.read_events(ctx.ledger_dir)) == before


def test_cycle_from_two_offline_devices_is_skipped_on_replay():
    """Each move was fine on its own laptop; together they loop. Replay must not hang,
    and the move that would close the loop is the one that doesn't apply."""
    events = [ev("a", T, "d1", 1, "CAS-01", "truck", "ADD"),
              ev("b", T, "d1", 2, "BAT-01", "truck", "ADD"),
              ev("c", T + timedelta(minutes=1), "d1", 3, "BAT-01", "CAS-01"),   # laptop 1
              ev("d", T + timedelta(minutes=2), "d2", 1, "CAS-01", "BAT-01")]   # laptop 2
    state = fold(events)
    assert ancestors(state, "BAT-01") == ["CAS-01", "truck"]
    assert [e.id for e in state.events] == ["a", "b", "c", "d"]   # still in the log, voidable


# --- latest wins -----------------------------------------------------------------

def test_latest_wins_whatever_order_the_files_are_read_in():
    events = [ev("a", T, "d1", 1, "BAT-01", "truck", "ADD"),
              ev("b", T + timedelta(minutes=1), "d2", 1, "BAT-01", "site-b"),
              ev("c", T + timedelta(minutes=2), "d1", 2, "BAT-01", "dock")]
    for seed_ in range(5):
        random.Random(seed_).shuffle(events)
        assert fold(events).where["BAT-01"] == "dock"


def test_same_device_orders_by_seq_even_if_its_clock_jumped_back():
    events = [ev("a", T, "d1", 1, "BAT-01", "truck", "ADD"),
              ev("b", T + timedelta(hours=1), "d1", 2, "BAT-01", "site-b"),
              ev("c", T + timedelta(minutes=5), "d1", 3, "BAT-01", "dock")]   # clock reset
    assert fold(events).where["BAT-01"] == "dock"


# --- the files are the record ----------------------------------------------------

def test_writes_go_to_the_event_files(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    with_case(ctx)
    on_disk = {e.id for e in store.read_events(ctx.ledger_dir)}
    assert on_disk == {e.id for e in store.load(ctx.conn)}
    assert run_git(ctx.ledger_dir, "status", "--porcelain") == ""


def test_replay_picks_up_files_from_a_git_pull(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    seed(ctx)
    pulled = ev("p", T + timedelta(days=1), "laptopb", 1, "BAT-02", "site-b")
    store.write_event(ctx.ledger_dir, pulled)          # arrives as a file, not via this cache
    reopened = make_ctx(tmp_path / "l.db")
    assert service.current_state(reopened).where["BAT-02"] == "site-b"


def test_cache_only_events_are_written_to_the_record(tmp_path):
    """A ledger from before the event files: its events get files on the next sync."""
    ctx = make_ctx(tmp_path / "l.db")
    old = ev("old", T, "d1", 1, "BAT-01", "truck", "ADD")
    store.cache(ctx.conn, [old])
    store.sync(ctx.conn, ctx.ledger_dir)
    assert store.read_events(ctx.ledger_dir) == [old]


def test_rebuild_is_identical(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    with_case(ctx)
    service.submit_move(ctx, Move("CAS-01", "van"))
    before = sorted(store.load(ctx.conn), key=lambda e: e.id)
    store.cache(ctx.conn, [ev("junk", T, "d9", 1, "BAT-02", "lost")])   # a damaged cache

    assert store.rebuild(ctx.conn, ctx.ledger_dir) == len(before)
    assert sorted(store.load(ctx.conn), key=lambda e: e.id) == before

    (tmp_path / "l.db").unlink()                       # the cache is gone entirely
    fresh = make_ctx(tmp_path / "l.db")
    assert sorted(store.load(fresh.conn), key=lambda e: e.id) == before
    assert service.current_state(fresh).where == service.current_state(ctx).where
