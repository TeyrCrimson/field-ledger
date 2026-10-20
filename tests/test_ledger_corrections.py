"""Corrections never edit history: VOID and RENAME are new events."""

import pytest

from field_ledger.ledger import service, store
from field_ledger.ledger.model import Kind, Move, Rename, Void
from ledger_helpers import Clock, make_ctx, seed


@pytest.fixture
def ctx(tmp_path):
    c = make_ctx(tmp_path / "l.db", clock=Clock())
    seed(c)
    return c


def test_rename_fixes_typo_everywhere_but_keeps_what_was_typed(ctx):
    service.submit_move(ctx, Move("BAT-01", "site-bb"), confirmed=True)
    out = service.submit_rename(ctx, Rename("site-bb", "site-b"))
    assert out.verdict.kind == Kind.ACCEPT
    assert service.current_state(ctx).where["BAT-01"] == "site-b"
    moves = [e for e in store.load(ctx.conn) if e.kind == "MOVE"]
    assert moves[0].dst == "site-bb"                    # original capture untouched


def test_moving_to_a_renamed_location_resolves_it(ctx):
    service.submit_move(ctx, Move("BAT-01", "site-bb"), confirmed=True)
    service.submit_rename(ctx, Rename("site-bb", "site-b"))
    out = service.submit_move(ctx, Move("BAT-02", "site-bb"))
    assert out.verdict.kind == Kind.ACCEPT              # known via the alias, no prompt


def test_rename_unknown_location_is_rejected(ctx):
    assert service.submit_rename(ctx, Rename("nowhere", "x")).verdict.kind == Kind.REJECT


def test_rename_loop_is_rejected(ctx):
    service.submit_move(ctx, Move("BAT-01", "dock"))
    service.submit_rename(ctx, Rename("dock", "pier"))
    service.submit_move(ctx, Move("BAT-02", "pier"))
    assert service.submit_rename(ctx, Rename("pier", "dock")).verdict.kind == Kind.REJECT


def test_void_restores_previous_location(ctx):
    moved = service.submit_move(ctx, Move("BAT-01", "site-b")).event
    out = service.submit_void(ctx, Void(moved.id[:8], "wrong battery"))
    assert out.verdict.kind == Kind.ACCEPT
    assert service.current_state(ctx).where["BAT-01"] == "truck"


def test_void_twice_is_rejected(ctx):
    moved = service.submit_move(ctx, Move("BAT-01", "site-b")).event
    service.submit_void(ctx, Void(moved.id, "oops"))
    out = service.submit_void(ctx, Void(moved.id, "again"))
    assert "already void" in out.verdict.messages[0]


def test_void_unknown_id_is_rejected(ctx):
    assert service.submit_void(ctx, Void("deadbeef", "x")).verdict.kind == Kind.REJECT
