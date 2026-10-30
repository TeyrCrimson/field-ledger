"""F4.2 end-of-day audit (Design Doc §5): every deployment day, each piece of kit is moved or
checked. A check is an AUD event, written only from the board's audit screen, never typed, so
checks never pose as moves. Found where the log has it: nothing moves. Found elsewhere or
missing (Lost): it's put there, and it counts as a mismatch. So does a Lost item turning up.
"""

import json
import shutil
import subprocess
import urllib.request
import uuid

import pytest

from field_ledger import hub
from field_ledger.ledger import service, store
from field_ledger.ledger.cli import main as fl
from field_ledger.ledger.kit import Group, plan_more
from field_ledger.ledger.model import Kind, Move
from field_ledger.ledger.state import fold, location_of
from field_ledger.ledger.store import read_events
from ledger_helpers import make_ctx, seed
from test_hub_writes import PHONE, board, post  # noqa: F401  (board is a fixture)


@pytest.fixture
def ctx(tmp_path):
    """BAT-01..03 and CAS-01 (a container) in the truck, CAM-01 at site-b, all added
    yesterday, so the whole kit is due today."""
    ctx = make_ctx(tmp_path / "l.db")
    seed(ctx)
    store.set_container(ctx.ledger_dir, "CAS", True)
    service.add_items(ctx, plan_more(Group("CAS", "Case", 1, "truck"), service.current_state(ctx)))
    ctx.now.advance(days=1)
    return ctx


def report(ctx):
    return service.audit_report(service.current_state(ctx), ctx.now())


def test_all_kit_untouched_today_is_due(ctx):
    due, wrong = report(ctx)
    assert due == ["BAT-01", "BAT-02", "BAT-03", "CAM-01", "CAS-01"] and wrong == []


def test_a_move_or_a_check_today_takes_it_off_the_list(ctx):
    service.submit_move(ctx, Move("BAT-01", "van"))
    service.submit_audit(ctx, "BAT-02")
    assert report(ctx)[0] == ["BAT-03", "CAM-01", "CAS-01"]


def test_carried_inside_a_case_still_needs_its_own_check(ctx):
    service.submit_move(ctx, Move("BAT-01", "CAS-01"))
    service.submit_audit(ctx, "CAS-01")                      # the case was seen, not the battery
    ctx.now.advance(days=1)
    service.submit_move(ctx, Move("CAS-01", "van"))
    assert "BAT-01" in report(ctx)[0]


def test_found_where_logged_moves_nothing(ctx):
    outcome = service.submit_audit(ctx, "bat-01")
    assert outcome.verdict.kind == Kind.ACCEPT
    e = outcome.event
    assert (e.kind, e.item, e.src, e.dst, e.flags) == ("AUD", "BAT-01", "truck", "truck", ())
    assert report(ctx)[1] == []


def test_found_elsewhere_puts_it_there_and_is_a_mismatch(ctx):
    service.submit_move(ctx, Move("BAT-01", "CAS-01"))
    outcome = service.submit_audit(ctx, "CAS-01", "site-b")
    assert outcome.verdict.kind == Kind.WARN and "mismatch" in outcome.event.flags
    assert outcome.verdict.messages[0] == "CAS-01 was logged in truck, found in site-b: a mismatch."
    state = service.current_state(ctx)
    assert location_of(state, "CAS-01") == location_of(state, "BAT-01") == "site-b"   # contents follow
    assert [e.item for e in report(ctx)[1]] == ["CAS-01"]


def test_missing_goes_to_lost_and_turning_up_is_a_mismatch_too(ctx):
    outcome = service.submit_audit(ctx, "BAT-03", "Lost")
    assert outcome.verdict.messages[0] == "BAT-03 was logged in truck, missing: a mismatch."
    ctx.now.advance(days=1)
    assert "BAT-03" not in report(ctx)[0]                   # can't be checked where it isn't
    service.submit_move(ctx, Move("BAT-03", "van"))
    assert [(e.kind, e.item) for e in report(ctx)[1]] == [("MOVE", "BAT-03")]


@pytest.mark.parametrize("item, found, message", [
    ("site-b", "", "'site-b' is not in the ledger."),       # a plain-string place: not kit
    ("BAT-01", "BAT-02", "BAT-02 can't hold things."),
    ("CAS-01", "CAS-01", "CAS-01 can't go into CAS-01: that's itself."),
    ("BAT-01", "BAT-09", "BAT-09 is not in the kit."),
])
def test_refused_checks_write_nothing(ctx, item, found, message):
    before = len(read_events(ctx.ledger_dir))
    outcome = service.submit_audit(ctx, item, found)
    assert outcome.verdict.kind == Kind.REJECT and outcome.event is None
    assert outcome.verdict.messages[0].startswith(message)
    assert len(read_events(ctx.ledger_dir)) == before


def test_builds_and_place_nodes_are_not_audited(ctx):
    service.submit_deploy(ctx, "feat/x", "drone-3")
    assert service.submit_audit(ctx, "feat/x").verdict.messages == (
        "feat/x is a build; its config is checked by CFG, not kit to audit.",)
    assert service.submit_audit(ctx, "drone-3").verdict.messages == (
        "drone-3 is a place, not kit to audit.",)
    assert "feat/x" not in report(ctx)[0] and "drone-3" not in report(ctx)[0]


def test_undo_takes_a_check_back(ctx):
    service.submit_audit(ctx, "BAT-01", "van")
    service.submit_undo(ctx)
    state = service.current_state(ctx)
    assert location_of(state, "BAT-01") == "truck" and "BAT-01" in report(ctx)[0]


# --- the CLI: read only ----------------------------------------------------------------

def test_fl_audit_lists_and_writes_nothing(tmp_path, capsys):
    db, ledger = str(tmp_path / "l.db"), str(tmp_path / "ledger")
    run = lambda *a: fl(["--db", db, "--ledger-dir", ledger, *a])   # noqa: E731
    assert run("init", "teyr") == 0
    assert run("add", "BAT", "2", "--at", "truck") == 0
    capsys.readouterr()
    before = len(read_events(tmp_path / "ledger"))
    assert run("audit") == 0
    assert capsys.readouterr().out.startswith("Audit due today: 0\nMismatches today: 0\n")  # just added
    assert len(read_events(tmp_path / "ledger")) == before
    assert run("run", "AUD BAT-01") == 1                    # no typed checks


# --- the board -------------------------------------------------------------------------

def test_state_json_has_the_audit(board):
    base, ledger, clock = board
    clock.advance(days=1)
    post(base, "audit", item="BAT-01", found="van", **PHONE)
    audit = json.loads(urllib.request.urlopen(f"{base}/state.json").read())["audit"]
    assert audit["due"] == ["BAT-02", "BAT-03", "CAM-01"]
    assert [(m["item"], m["logged"], m["found"], m["by"]) for m in audit["mismatches"]] == \
        [("BAT-01", "truck", "van", "Yoeng")]


def test_check_from_the_board(board):
    base, ledger, clock = board
    status, here = post(base, "audit", item="BAT-01", **PHONE)
    assert here["readback"] == "✓ BAT-01 · Battery · checked in truck"
    status, there = post(base, "audit", item="BAT-02", found="site-b", **PHONE)
    assert there["verdict"] == "WARN"
    assert there["readback"] == "AUD BAT-02 · Battery · logged in truck, found in site-b"
    assert location_of(fold(read_events(ledger)), "BAT-02") == "site-b"


def test_a_queued_check_the_hub_refuses_is_held(board):
    base, ledger, _ = board
    body = {"id": str(uuid.uuid4()), "item": "BAT-09", **PHONE}
    status, answer = post(base, "audit", **body, queued=True)
    assert answer["held"] is True and store.needs_a_look(ledger)[0]["command"] == "audit"


HARNESS = """
class El {
  constructor(tag) { this.tag = tag; this.kids = []; this.on = {}; this.parent = null; }
  setAttribute() {}
  append(...kids) { for (const k of kids) if (typeof k === "object") { k.parent = this; this.kids.push(k); } }
  remove() { this.parent.kids.splice(this.parent.kids.indexOf(this), 1); }
  addEventListener(type, fn) { (this.on[type] ??= []).push(fn); }
  all(tag) { return this.kids.flatMap((k) => [...(k.tag === tag ? [k] : []), ...k.all(tag)]); }
}
globalThis.document = { createElement: (tag) => new El(tag) };
const { auditDialog } = await import("./components/audit.js");
const sent = [];
const nodes = [{ id: "BAT-01", group: "Battery", location: "truck", chain: ["truck"] },
               { id: "CAM-01", group: "Camera", location: "site-b", chain: ["site-b"] }];
const dialog = auditDialog({ due: ["BAT-01", "CAM-01"], mismatches: [] }, nodes, ["truck"],
                           (item, found) => sent.push([item, found]));
const tap = (text) => dialog.all("button").find((b) => b.textContent === text).on.click[0]();
const places = dialog.all("h3").map((h) => h.textContent);
tap("✓ Here");
tap("Missing");
console.log(JSON.stringify({ places, sent, left: dialog.all("button").map((b) => b.textContent) }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_audit_screen_checks_one_item_per_tap():
    out = subprocess.run(["node", "--input-type=module", "-e", HARNESS], cwd=hub.WEB_DIR,
                         capture_output=True, text=True, check=True, timeout=10)
    result = json.loads(out.stdout)
    assert result["places"] == ["truck", "site-b"]
    assert result["sent"] == [["BAT-01", ""], ["CAM-01", "lost"]]
    assert result["left"] == ["Done"]                       # each checked row is gone
