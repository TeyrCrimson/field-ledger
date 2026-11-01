"""F4.4 field-ops owner (Design Doc §3, Trust): each ledger has an owner who is nudged about
unresolved ⚠s. `fl init` makes its creator the owner, and nothing moves in a ledger with none
(Teyr, 2026-10-30). Only the owner hands over; with no owner, anyone takes it; once the nudge
has gone unanswered for `nudge_after` (1 day: every day counts), anyone may claim it for
themselves. The nudge is worked out from the open ⚠s on every read; nothing is written.
"""

import json
import shutil
import subprocess
import urllib.request

import pytest

from field_ledger import hub
from field_ledger.ledger import service, store
from field_ledger.ledger.cli import main as fl
from field_ledger.ledger.model import Kind, Move
from field_ledger.ledger.state import fold
from field_ledger.ledger.store import read_events
from ledger_helpers import Clock, make_ctx, seed
from test_hub_writes import PHONE, board, post  # noqa: F401  (board is a fixture)


@pytest.fixture
def ctx(tmp_path):
    """teyr's ledger (teyr owns it, as after `fl init`), with Ivan and Yoeng on the list."""
    ctx = make_ctx(tmp_path / "l.db", "teyr")
    seed(ctx)
    for name in ("Ivan", "Yoeng"):
        store.add_person(ctx.ledger_dir, name)
    return ctx


@pytest.fixture
def ownerless(tmp_path):
    """A ledger made before owners existed: kit in it, nobody owns it."""
    ledger = tmp_path / "old-ledger"
    store.init_ledger(ledger)
    conn = store.connect(tmp_path / "old.db")
    ctx = service.Context(conn, "Yoeng", store.ensure_device(conn), Clock(), ledger)
    for name in ("teyr", "Ivan", "Yoeng"):
        store.add_person(ledger, name)
    seed(ctx)
    return ctx


def as_(ctx, actor, device=None):
    """The same ledger and clock, as someone else on another device."""
    return service.Context(ctx.conn, actor, device or f"dev-{actor}", ctx.now, ctx.ledger_dir)


def conflict(ctx):
    """BAT-02 moved to two places by two devices a minute apart: one open ⚠."""
    service.submit_move(as_(ctx, "Yoeng", "phone-a"), Move("BAT-02", "van"))
    ctx.now.advance(minutes=1)
    service.submit_move(as_(ctx, "Ivan", "phone-b"), Move("BAT-02", "site-b"))


def owner(ctx):
    state = fold(read_events(ctx.ledger_dir))
    return state.owner.dst if state.owner else ""


def test_nothing_moves_without_an_owner(ownerless):
    message = ("This ledger has no field-ops owner yet, so nothing can be moved. "
               "`fl owner <name>` (or Owner on the board) sets one.",)
    before = len(read_events(ownerless.ledger_dir))
    assert service.submit_move(ownerless, Move("BAT-01", "van")).verdict.messages == message
    assert service.submit_deploy(ownerless, "feat/x", "drone-3").verdict.messages == message
    assert service.submit_audit(ownerless, "BAT-01", "van").verdict.messages == message
    assert service.submit_audit(ownerless, "BAT-01").event is not None      # a check moves nothing
    assert len(read_events(ownerless.ledger_dir)) == before + 1


def test_anyone_takes_it_when_there_is_none_and_then_things_move(ownerless):
    outcome = service.submit_owner(ownerless, "ivan")             # spelled as the list has it
    assert outcome.verdict.kind == Kind.ACCEPT and owner(ownerless) == "Ivan"
    assert (outcome.event.kind, outcome.event.src, outcome.event.dst) == ("OWNER", "", "Ivan")
    assert service.submit_move(ownerless, Move("BAT-01", "van")).event is not None


def test_only_the_owner_hands_over(ctx):
    refused = service.submit_owner(as_(ctx, "Ivan"), "Yoeng")
    assert refused.verdict.messages == ("Only teyr can hand the field-ops owner over.",)
    taken = service.submit_owner(as_(ctx, "Ivan"), "Ivan")         # no ⚠: no nudge to miss
    assert taken.verdict.kind == Kind.REJECT and "once a ⚠ nudge goes unanswered" in taken.verdict.messages[0]
    assert service.submit_owner(ctx, "Yoeng").event.src == "teyr" and owner(ctx) == "Yoeng"


def test_a_nudge_unanswered_for_a_day_lets_anyone_claim(ctx):
    conflict(ctx)
    ctx.now.advance(hours=23)
    early = service.submit_owner(as_(ctx, "Ivan"), "Ivan")
    assert early.verdict.kind == Kind.REJECT and "A ⚠ has waited 23 h; after 24 h" in early.verdict.messages[0]
    assert not service.owner_report(service.current_state(ctx), ctx.now())["claimable"]
    ctx.now.advance(hours=1)                                       # a Saturday counts like any day
    assert service.owner_report(service.current_state(ctx), ctx.now())["claimable"]
    assert service.submit_owner(as_(ctx, "Ivan"), "Yoeng").verdict.kind == Kind.REJECT   # for yourself only
    claim = service.submit_owner(as_(ctx, "Ivan"), "Ivan")
    assert claim.verdict.kind == Kind.WARN and claim.event.flags == ("claimed",)
    assert claim.verdict.messages == ("teyr left a ⚠ unanswered for 24 h: Ivan takes over.",)


def test_settling_the_conflict_answers_the_nudge(ctx):
    conflict(ctx)
    ctx.now.advance(days=2)
    service.submit_resolve(ctx, "BAT-02", "van")
    report = service.owner_report(service.current_state(ctx), ctx.now())
    assert (report["open"], report["nudged_since"], report["claimable"]) == (0, None, False)


def test_a_new_owner_gets_a_full_day(ctx):
    conflict(ctx)
    ctx.now.advance(days=2)
    service.submit_owner(as_(ctx, "Ivan"), "Ivan")                 # claimed after two days
    ctx.now.advance(hours=1)
    assert service.submit_owner(as_(ctx, "Yoeng"), "Yoeng").verdict.kind == Kind.REJECT


@pytest.mark.parametrize("to, message", [("Stranger", "'Stranger' isn't on the People list."),
                                         ("teyr", "teyr is already the field-ops owner.")])
def test_refusals_write_nothing(ctx, to, message):
    before = len(read_events(ctx.ledger_dir))
    assert service.submit_owner(ctx, to).verdict.messages == (message,)
    assert len(read_events(ctx.ledger_dir)) == before


def test_undo_takes_a_handover_back(ctx):
    ctx.now.advance(minutes=1)
    service.submit_owner(ctx, "Ivan")
    service.submit_undo(ctx)
    assert owner(ctx) == "teyr"


# --- the CLI ---------------------------------------------------------------------------

def test_fl_owner(tmp_path, capsys):
    db, ledger = str(tmp_path / "l.db"), str(tmp_path / "ledger")
    run = lambda *a: fl(["--db", db, "--ledger-dir", ledger, *a])   # noqa: E731
    assert run("init", "teyr") == 0
    assert capsys.readouterr().out.rstrip().endswith("field-ops owner: teyr")   # whoever makes it
    assert run("owner") == 0
    assert capsys.readouterr().out == "Field-ops owner: teyr\n"
    assert run("owner", "Ivan") == 1                              # not on the People list
    assert run("people", "add", "Ivan") == 0
    assert run("owner", "Ivan") == 0
    assert "OWNER teyr → Ivan" in capsys.readouterr().out
    assert run("--actor", "Ivan", "init", "Ivan") == 0            # a second init keeps the owner
    assert "field-ops owner: Ivan" in capsys.readouterr().out


# --- the board -------------------------------------------------------------------------

def test_state_json_and_a_handover_from_the_board(board):
    base, ledger, _ = board
    status, refused = post(base, "owner", to="Yoeng", **PHONE)      # Yoeng isn't the owner
    assert refused["verdict"] == "REJECT"
    status, answer = post(base, "owner", to="Yoeng", actor="teyr", device="laptop")
    assert answer["readback"] == "OWNER teyr → Yoeng"
    served = json.loads(urllib.request.urlopen(f"{base}/state.json").read())["owner"]
    assert (served["name"], served["open"], served["claimable"]) == ("Yoeng", 0, False)


HARNESS = """
class El {
  constructor(tag) { this.tag = tag; this.kids = []; this.on = {}; }
  setAttribute() {}
  append(...kids) { for (const k of kids) if (typeof k === "object") this.kids.push(k); }
  addEventListener(type, fn) { (this.on[type] ??= []).push(fn); }
  all(tag) { return this.kids.flatMap((k) => [...(k.tag === tag ? [k] : []), ...k.all(tag)]); }
}
globalThis.document = { createElement: (tag) => new El(tag) };
const { nudgeBanner, ownerDialog } = await import("./components/owner.js");
const labels = (node) => node ? node.all("button").map((b) => b.textContent) : null;
const people = ["teyr", "Ivan", "Yoeng"];
const waiting = { name: "teyr", open: 1, claimable: false };
const late = { name: "teyr", open: 1, claimable: true };
let shown = 0;
const tapped = nudgeBanner(late, "Ivan", () => {}, () => shown++);
tapped.on.click[0]({ target: { closest: () => null } });          // the banner itself
tapped.on.click[0]({ target: { closest: () => ({}) } });          // its Take over button
console.log(JSON.stringify({
  quiet: nudgeBanner({ name: "teyr", open: 0, claimable: false }, "Ivan", () => {}),
  waiting: labels(nudgeBanner(waiting, "Ivan", () => {})),
  late: labels(nudgeBanner(late, "Ivan", () => {})),
  ownerSees: labels(ownerDialog(waiting, people, "teyr", () => {})),
  othersSee: labels(ownerDialog(waiting, people, "Ivan", () => {})),
  claim: labels(ownerDialog(late, people, "Ivan", () => {})),
  shown,
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_board_offers_only_what_the_hub_would_accept():
    out = subprocess.run(["node", "--input-type=module", "-e", HARNESS], cwd=hub.WEB_DIR,
                         capture_output=True, text=True, check=True, timeout=10)
    assert json.loads(out.stdout) == {
        "quiet": None, "waiting": [], "late": ["Take over"],
        "ownerSees": ["Ivan", "Yoeng", "Close"], "othersSee": ["Close"],
        "claim": ["Take over", "Close"], "shown": 1}
