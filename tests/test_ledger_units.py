"""Small pure pieces: ID rules, kit file, ordering."""

from datetime import datetime, timezone

import pytest

from field_ledger.ledger.ids import canonical_item, canonical_location, expand_group
from field_ledger.ledger.kit import Group, plan_kit, plan_more, read_kit
from field_ledger.ledger.model import Event
from field_ledger.ledger.state import State, fold

T = datetime(2026, 10, 17, tzinfo=timezone.utc)


@pytest.mark.parametrize("raw,expected", [
    ("bat7", "BAT-07"), ("BAT-07", "BAT-07"), ("bat 007", "BAT-07"), ("CAM-123", "CAM-123"),
    ("BA-07", None), ("BATT-07", None), ("BAT-", None), ("07", None),
])
def test_canonical_item(raw, expected):
    assert canonical_item(raw) == expected


def test_canonical_location():
    assert canonical_location("  Yoeng's   Bag ") == "yoeng's bag"


def test_expand_group():
    assert expand_group("bat", 9, 2) == ["BAT-09", "BAT-10"]


def test_kit_file_parses_and_validates():
    groups = read_kit("prefix,name,count,location\nBAT,Battery,2,Truck\n")
    assert groups == [Group("BAT", "Battery", 2, "truck")]
    with pytest.raises(ValueError, match="exactly 3 letters"):
        read_kit("prefix,name,count,location\nBA1,x,1,truck\n")


def test_add_continues_numbering_for_existing_group():
    state = State(items={"BAT-01": "Battery", "BAT-02": "Battery"})
    planned = plan_more(Group("BAT", "Battery", 2, "truck"), state)
    assert [p.item for p in planned] == ["BAT-03", "BAT-04"]


def test_kit_only_fills_missing_items():
    state = State(items={"BAT-01": "Battery", "BAT-03": "Battery"})
    planned = plan_kit(Group("BAT", "Battery", 4, "truck"), state)
    assert [p.item for p in planned] == ["BAT-02", "BAT-04"]


def test_same_timestamp_orders_by_sequence():
    add = Event("a", T, "d1", 1, "t", "ADD", item="BAT-01", dst="truck")
    m2 = Event("c", T, "d1", 3, "t", "MOVE", item="BAT-01", dst="dock")
    m1 = Event("b", T, "d1", 2, "t", "MOVE", item="BAT-01", dst="site-b")
    assert fold([m2, add, m1]).where["BAT-01"] == "dock"
