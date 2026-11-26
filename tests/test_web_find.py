"""Find an item from the Menu (Teyr, 2026-11-02; agreed 2026-11-14): an ID, part of a name or
a serial lists matching items and places with where each one is, innermost first. Runs the
real find.js in node against a stand-in DOM. Needs `node`. The hub side (serial in the
snapshot) is tested here too, as it exists for Find."""

import json
import shutil
import subprocess
from datetime import datetime, timezone

import pytest

from field_ledger import hub
from field_ledger.ledger.model import Event
from field_ledger.ledger.state import fold

node = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")

NODES = [
    {"id": "hq", "group": "location", "fixed": True, "chain": []},
    {"id": "VAN-01", "group": "Van", "chain": ["hq"]},
    {"id": "CAS-01", "group": "Pelican case", "chain": ["VAN-01", "hq"]},
    {"id": "BAT-12", "group": "Blue 6S", "chain": ["CAS-01", "VAN-01", "hq"]},
    {"id": "BAT-01", "group": "Blue 6S", "chain": ["site-b"]},
    {"id": "CAM-01", "group": "SIYI camera", "serial": "SN-0042", "chain": ["site-b"]},
    {"id": "feat-x", "group": "build", "chain": []},
]
PLACES = ["hq", "site-b"]

HARNESS = """
class El {
  constructor(tag) { this.tag = tag; this.kids = []; this.on = {}; this.attrs = {}; this.textContent = ""; }
  setAttribute(k, v) { this.attrs[k] = v; }
  append(...kids) { this.kids.push(...kids.filter((k) => typeof k === "object")); }
  replaceChildren(...kids) { this.kids = kids; }
  addEventListener(type, fn) { (this.on[type] ??= []).push(fn); }
}
globalThis.document = { createElement: (tag) => new El(tag) };
const { findNodes, findDialog } = await import("./components/find.js");
const [nodes, places, queries] = JSON.parse(process.argv[1]);
const results = Object.fromEntries(queries.map((q) => [q, findNodes(nodes, places, q)]));
const dialog = findDialog(nodes, places);
const [, input, status, list] = dialog.kids;
const typed = (text) => {
  input.value = text;
  input.on.input[0]();
  return { status: status.textContent,
           lines: list.kids.map((li) => li.kids.map((span) => span.textContent)) };
};
console.log(JSON.stringify({ results, nested: typed("bat 12"), none: typed("zzz"),
                             empty: typed("  "), focus: input.autofocus }));
"""

QUERIES = ["BAT-12", "bat12", "6s", "sn-0042", "0042", "site", "hq", "zzz", "", "bat", "feat"]


@pytest.fixture(scope="module")
def run():
    if shutil.which("node") is None:
        pytest.skip("needs node")
    out = subprocess.run(["node", "--input-type=module", "-e", HARNESS,
                          json.dumps([NODES, PLACES, QUERIES])],
                         cwd=hub.WEB_DIR, capture_output=True, text=True, check=True, timeout=10)
    return json.loads(out.stdout)


def ids(run, query):
    return [hit["id"] for hit in run["results"][query]]


@node
def test_id_match_ignores_case_and_separators(run):
    assert ids(run, "BAT-12") == ids(run, "bat12") == ["BAT-12"]


@node
def test_name_match(run):
    assert ids(run, "6s") == ["BAT-01", "BAT-12"]


@node
def test_serial_match(run):
    assert ids(run, "sn-0042") == ids(run, "0042") == ["CAM-01"]
    assert run["results"]["0042"][0]["serial"] == "SN-0042"


@node
def test_places_match_both_nodes_and_plain_names(run):
    assert ids(run, "site") == ["site-b"]                          # a place that is only a name
    assert run["results"]["hq"][0] == {"id": "hq", "name": "location", "serial": "",
                                       "where": "a place"}       # a place node, listed once


@node
def test_exact_id_comes_first(run):
    assert ids(run, "hq")[0] == "hq"


@node
def test_nested_item_reads_innermost_first(run):
    assert run["nested"] == {"status": "",
                             "lines": [["BAT-12 · Blue 6S", "CAS-01 in VAN-01 at hq"]]}


@node
def test_no_match_and_empty_query(run):
    assert run["results"]["zzz"] == [] and run["none"] == {"status": "Nothing matches.", "lines": []}
    assert run["results"][""] == [] and run["empty"] == {"status": "", "lines": []}


@node
def test_unplaced_build_says_so_and_input_takes_focus(run):
    assert [h["where"] for h in run["results"]["bat"]] == ["site-b", "CAS-01 in VAN-01 at hq"]
    assert [h["where"] for h in run["results"]["feat"]] == ["nowhere yet"]
    assert run["focus"] is True


def test_snapshot_carries_a_serial_only_when_set():
    t = datetime(2026, 11, 14, tzinfo=timezone.utc)
    add = lambda n, item, serial="": Event(id=f"e{n}", ts=t, device="d", seq=n, actor="teyr",
                                            kind="ADD", item=item, dst="hq", note="Camera",
                                            serial=serial)
    board = hub.snapshot(fold([add(1, "CAM-01", "SN-1"), add(2, "CAM-02")]), {}, t)
    by_id = {n["id"]: n for n in board["nodes"]}
    assert by_id["CAM-01"]["serial"] == "SN-1" and "serial" not in by_id["CAM-02"]
