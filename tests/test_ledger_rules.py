"""The accept/reject table, one test per row. These are the behaviour contract."""

import pytest

from field_ledger.ledger import service
from field_ledger.ledger.model import Kind, Move
from field_ledger.ledger.parse import ParseError, parse
from ledger_helpers import Clock, make_ctx, seed


@pytest.fixture
def ctx(tmp_path):
    c = make_ctx(tmp_path / "l.db", clock=Clock())
    seed(c)
    return c


def where(ctx, item):
    return service.current_state(ctx).where[item]


def test_plain_move_is_accepted(ctx):
    out = service.submit_move(ctx, parse("MOVE BAT-01 > site-B"))
    assert out.verdict.kind == Kind.ACCEPT
    assert where(ctx, "BAT-01") == "site-b"


def test_case_and_whitespace_are_normalised(ctx):
    out = service.submit_move(ctx, parse("move  bat-01   >   Site-B "))
    assert out.verdict.kind == Kind.ACCEPT
    assert out.event.dst == "site-b"


@pytest.mark.parametrize("raw", ["BAT01", "bat1", "BAT 1", "bat_001"])
def test_id_format_variants_map_to_one_id(ctx, raw):
    out = service.submit_move(ctx, Move(raw, "site-b"))
    assert out.event.item == "BAT-01"


def test_misspelt_item_is_rejected_with_suggestion(ctx):
    out = service.submit_move(ctx, Move("BTA-01", "site-b"))
    assert out.verdict.kind == Kind.REJECT
    assert "Did you mean BAT-01?" in out.verdict.messages[0]


def test_item_not_in_kit_is_rejected(ctx):
    out = service.submit_move(ctx, Move("BAT-99", "site-b"))
    assert out.verdict.kind == Kind.REJECT and out.event is None


def test_origin_mismatch_is_written_and_flagged(ctx):
    out = service.submit_move(ctx, parse("MOVE BAT-01 site-b > case-1"))
    assert out.verdict.kind == Kind.WARN
    assert "from-mismatch" in out.event.flags
    assert where(ctx, "BAT-01") == "case-1"


def test_double_tap_within_window_is_ignored(ctx):
    service.submit_move(ctx, Move("BAT-01", "site-b"))
    ctx.now.advance(seconds=30)
    assert service.submit_move(ctx, Move("BAT-01", "site-b")).verdict.kind == Kind.IGNORE


def test_a_double_tap_says_how_long_ago_not_a_clock_time(ctx):
    """A clock time came out in the zone the event was stamped in: UTC for a phone, so 23:59
    in Singapore read 15:59 (Teyr, 2026-11-01). How long ago is the same everywhere."""
    service.submit_move(ctx, Move("BAT-01", "site-b"))
    assert service.submit_move(ctx, Move("BAT-01", "site-b")).verdict.messages == (
        "Already logged BAT-01 -> 'site-b' just now.",)
    ctx.now.advance(seconds=90)
    assert service.submit_move(ctx, Move("BAT-01", "site-b")).verdict.messages == (
        "Already logged BAT-01 -> 'site-b' 1 min ago.",)


def test_same_move_after_window_needs_confirmation_not_ignored(ctx):
    service.submit_move(ctx, Move("BAT-01", "site-b"))
    ctx.now.advance(minutes=3)
    assert service.submit_move(ctx, Move("BAT-01", "site-b")).verdict.kind == Kind.CONFIRM


def test_same_place_asks_and_writes_nothing_until_confirmed(ctx):
    first = service.submit_move(ctx, Move("BAT-01", "truck"))
    assert first.verdict.kind == Kind.CONFIRM and first.event is None
    second = service.submit_move(ctx, Move("BAT-01", "truck"), confirmed=True)
    assert set(second.event.flags) == {"same-place", "confirmed"}


def test_missing_destination_is_a_parse_error():
    with pytest.raises(ParseError, match="Usage: MOVE"):
        parse("MOVE BAT-01")


def test_location_close_to_a_known_one_asks_did_you_mean(ctx):
    out = service.submit_move(ctx, Move("BAT-01", "site-bb"))
    assert out.verdict.kind == Kind.CONFIRM
    assert "Did you mean 'site-b'?" in out.verdict.messages[0]


def test_unrelated_new_location_is_written_and_flagged(ctx):
    out = service.submit_move(ctx, Move("BAT-01", "Yoeng's bag"))
    assert out.verdict.kind == Kind.WARN
    assert out.event.flags == ("new-location",)
