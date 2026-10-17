"""Kit creation: groups of items with a 3-letter prefix, numbered from 01.

Kit file (CSV, header required):
    prefix,name,count,location
    BAT,Battery,12,truck
    CAM,SIYI camera,3,case-1
"""

import csv
import io
import re
from dataclasses import dataclass

from .ids import canonical_location, expand_group, is_prefix
from .state import State

NUMBER_RE = re.compile(r"-(\d+)$")


@dataclass(frozen=True)
class Group:
    prefix: str
    name: str
    count: int
    location: str


@dataclass(frozen=True)
class PlannedAdd:
    item: str
    name: str
    location: str


def parse_group(row: dict) -> Group:
    """One CSV row -> Group. Raises ValueError with a readable message."""
    prefix = (row.get("prefix") or "").strip()
    if not is_prefix(prefix):
        raise ValueError(f"prefix '{prefix}' must be exactly 3 letters")
    count = int((row.get("count") or "0").strip())
    if count < 1:
        raise ValueError(f"{prefix}: count must be at least 1")
    location = canonical_location(row.get("location") or "")
    if not location:
        raise ValueError(f"{prefix}: a starting location is required")
    return Group(prefix.upper(), (row.get("name") or prefix).strip(), count, location)


def read_kit(text: str) -> list[Group]:
    return [parse_group(row) for row in csv.DictReader(io.StringIO(text))]


def group_numbers(prefix: str, state: State) -> list[int]:
    return [int(NUMBER_RE.search(item).group(1))
            for item in state.items if item.startswith(f"{prefix}-")]


def next_number(prefix: str, state: State) -> int:
    return max(group_numbers(prefix, state), default=0) + 1


def plan_kit(group: Group, state: State) -> list[PlannedAdd]:
    """Kit file semantics: the group should have items 01..count. Create only the missing ones,
    so re-running the same kit file changes nothing."""
    return [PlannedAdd(item, group.name, group.location)
            for item in expand_group(group.prefix, 1, group.count) if item not in state.items]


def plan_more(group: Group, state: State) -> list[PlannedAdd]:
    """`fl add` semantics: `count` more items, numbered after the highest existing one."""
    start = next_number(group.prefix, state)
    return [PlannedAdd(item, group.name, group.location)
            for item in expand_group(group.prefix, start, group.count)]
