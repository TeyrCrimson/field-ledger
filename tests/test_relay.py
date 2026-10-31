"""F4.5 the Telegram relay: phones that can't reach the hub send their waiting writes through
the team's bot, and the hub fetches them over outbound HTTPS. A typed move gets asked for a
time (marked `prompted`); WHERE and AT are answered. Only linked people get anything back.
Tested against a fake Telegram server: no token, no network.
"""

import json
import shutil
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from field_ledger import hub, relay
from field_ledger.ledger import store
from field_ledger.ledger.cli import main as fl
from field_ledger.ledger.state import fold, location_of
from field_ledger.ledger.store import read_events
from ledger_helpers import make_ctx, seed

YOENG = 4242                                  # a Telegram user id


@pytest.fixture
def the_hub(tmp_path):
    """teyr's ledger (BAT-01..03 in the truck, CAM-01 at site-b), Yoeng on the list and
    linked to Telegram user 4242."""
    ctx = make_ctx(tmp_path / "l.db")
    seed(ctx)
    store.add_person(ctx.ledger_dir, "Yoeng")
    code = store.link_code(ctx.ledger_dir, "Yoeng")
    assert store.use_link_code(ctx.ledger_dir, code, str(YOENG)) == "Yoeng"
    return hub.Hub(ctx.ledger_dir, db=tmp_path / "hub.db", now=ctx.now)


def message(text, user=YOENG, message_id=1, sent=None):
    sent = sent or datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)
    return {"message_id": message_id, "from": {"id": user}, "chat": {"id": user},
            "date": int(sent.timestamp()), "text": text}


def queued(command, **body):
    """A write as the phone stamps it."""
    return {"command": command, "body": {"id": str(uuid.uuid4()), "device": "web-a1b2c3d4", "seq": 3,
                                         "occurred_at": "2026-10-17T02:50:00+00:00",
                                         "actor": "whoever", **body}}


def relayed(*writes):
    return "\n".join(f"line for people\n#fl {json.dumps(w)}" for w in writes)


def events(the_hub):
    return read_events(the_hub.ledger_dir)


# --- pure parts --------------------------------------------------------------------------

def test_payload_lines_are_read_and_junk_skipped():
    write = queued("move", item="BAT-01", to="van")
    text = f"BAT-01 → van\n#fl {json.dumps(write)}\n#fl not json\n#fl [1]\nhello"
    assert relay.payload_writes(text) == [("move", write["body"])]


@pytest.mark.parametrize("reply, expected", [
    ("now", (3, 0, 17)), ("02:30", (2, 30, 17)), ("2.30", (2, 30, 17)), ("0230", (2, 30, 17)),
    ("23:50", (23, 50, 16)),                                    # later than sent: the day before
    ("25:00", None), ("soon", None),
])
def test_asked_times(reply, expected):
    sent = datetime(2026, 10, 17, 3, 0).astimezone()            # 03:00 on this machine's clock
    when = relay.asked_time(reply, sent)
    if expected is None:
        assert when is None
    else:
        assert (when.hour, when.minute, when.day) == expected


# --- who it talks to -----------------------------------------------------------------------

def test_strangers_get_nothing_and_a_code_links_once(the_hub, tmp_path):
    stranger = message("WHERE BAT-01", user=99)
    assert relay.handle(the_hub, stranger, {}) == "I don't know you yet. Ask the field-ops owner for a link code."
    code = store.link_code(the_hub.ledger_dir, "teyr")
    assert relay.handle(the_hub, message(f"/start {code}", user=99), {}) == \
        "Hello, teyr. Moves you send here go into the ledger."
    assert relay.handle(the_hub, message(f"/start {code}", user=100), {}).startswith("I don't know you")
    assert relay.handle(the_hub, stranger, {}) == "BAT-01: truck"


def test_fl_people_link(tmp_path, capsys):
    db, ledger = str(tmp_path / "l.db"), str(tmp_path / "ledger")
    run = lambda *a: fl(["--db", db, "--ledger-dir", ledger, *a])   # noqa: E731
    assert run("init", "teyr") == 0
    assert run("people", "link", "Nobody") == 1
    capsys.readouterr()
    assert run("people", "link", "TEYR") == 0
    code = capsys.readouterr().out.split("/start ")[1].split()[0]
    assert store.use_link_code(tmp_path / "ledger", code, "7") == "teyr"


# --- a phone's waiting writes ---------------------------------------------------------------

def test_waiting_writes_are_logged_as_the_linked_person_once(the_hub):
    move = queued("move", item="BAT-01", to="site-b")
    first = relay.handle(the_hub, message(relayed(move)), {})
    assert first == "✓ BAT-01 · Battery · was in truck → site-b"
    e = next(e for e in events(the_hub) if e.id == move["body"]["id"])
    assert (e.actor, e.device, e.seq, e.ts.isoformat()) == \
        ("Yoeng", "web-a1b2c3d4", 3, "2026-10-17T02:50:00+00:00")    # the sender, the phone's stamp
    assert relay.handle(the_hub, message(relayed(move), message_id=2), {}) == "Already logged."


def test_a_refused_write_is_held_and_hub_only_writes_are_not_relayed(the_hub):
    bad = queued("move", item="BAT-09", to="van")
    undo = queued("undo")
    reply = relay.handle(the_hub, message(relayed(bad, undo)), {})
    held, not_relayed = reply.splitlines()
    assert held.startswith("Needs a look on the board: BAT-09 is not in the kit.")
    assert not_relayed == "Not logged: 'undo' needs the hub itself."
    assert store.needs_a_look(the_hub.ledger_dir)[0]["id"] == bad["body"]["id"]


# --- typed moves and questions -----------------------------------------------------------

def test_a_typed_move_is_asked_for_a_time_and_marked_prompted(the_hub):
    pending = {}
    assert relay.handle(the_hub, message("MOVE BAT-02 > site-b"), pending) == relay.ASK_TIME
    assert not any(e.item == "BAT-02" and e.kind == "MOVE" for e in events(the_hub))
    reply = relay.handle(the_hub, message("now", message_id=2), pending)
    assert reply == "✓ BAT-02 · Battery · was in truck → site-b" and pending == {}
    e = next(e for e in events(the_hub) if e.item == "BAT-02" and e.kind == "MOVE")
    assert (e.actor, e.device, e.time_source) == ("Yoeng", f"telegram-{YOENG}", "prompted")
    assert e.ts == datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)


def test_a_time_after_the_move_logs_it_at_once(the_hub):
    sent = datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)
    assert relay.handle(the_hub, message("MOVE BAT-03 > van @now", sent=sent), {}).startswith("✓ BAT-03")
    assert location_of(fold(events(the_hub)), "BAT-03") == "van"
    again = relay.handle(the_hub, message("MOVE BAT-03 > van @now", sent=sent), {})   # a refetch
    assert again == "Already logged."


@pytest.mark.parametrize("when", ["now", ":", "."])
def test_a_bare_time_at_the_end_is_the_time_not_part_of_the_place(the_hub, when):
    """`MOVE BAT-01 > truck now` logged a place called "truck now" (Teyr, 2026-11-01)."""
    local = datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc).astimezone()   # when it's sent
    when = when if when == "now" else f"{local.hour}{when}{local.minute:02}"
    assert relay.handle(the_hub, message(f"move BAT-03 > van {when}"), {}).startswith("✓ BAT-03")
    assert location_of(fold(events(the_hub)), "BAT-03") == "van"


def test_a_number_at_the_end_with_no_colon_stays_in_the_place(the_hub):
    pending = {}
    assert relay.handle(the_hub, message("MOVE BAT-03 > Gate 1430"), pending) == relay.ASK_TIME
    relay.handle(the_hub, message("now", message_id=2), pending)
    assert location_of(fold(events(the_hub)), "BAT-03") == "gate 1430"          # places are kept in lower case


def test_questions_and_everything_else(the_hub):
    assert relay.handle(the_hub, message("where bat-1"), {}) == "BAT-01: truck"
    assert relay.handle(the_hub, message("AT site-b"), {}) == "At site-b: CAM-01"
    assert relay.handle(the_hub, message("RENAME truck > lorry"), {}).startswith("Only moves come through")
    assert relay.handle(the_hub, message("hello"), {}).startswith("unknown command 'HELLO'")


# --- polling a (fake) Telegram -------------------------------------------------------------

class FakeTelegram(BaseHTTPRequestHandler):
    updates: list = []
    sent: list = []
    offsets: list = []

    def do_POST(self):
        method = self.path.rsplit("/", 1)[1]
        params = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if method == "getUpdates":
            self.offsets.append(params["offset"])
            result = [u for u in self.updates if u["update_id"] >= params["offset"]]
        elif method == "sendMessage":
            self.sent.append(params)
            result = {}
        else:
            result = {"username": "casio_ledger_bot"}
        body = json.dumps({"ok": True, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_polling_answers_and_never_handles_an_update_twice(the_hub):
    FakeTelegram.updates = [{"update_id": 10, "message": message("WHERE BAT-01")},
                            {"update_id": 11, "message": message("MOVE BAT-01 > van @now", message_id=2)}]
    FakeTelegram.sent, FakeTelegram.offsets = [], []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeTelegram)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    api = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert relay.poll_once(the_hub, "TOKEN", {}, api, wait=0) == 2
        assert relay.poll_once(the_hub, "TOKEN", {}, api, wait=0) == 0         # a restarted hub too
    finally:
        server.shutdown()
    assert FakeTelegram.offsets == [0, 12]
    assert [s["text"] for s in FakeTelegram.sent] == ["BAT-01: truck",
                                                      "✓ BAT-01 · Battery · was in truck → van"]
    assert FakeTelegram.sent[1]["reply_to_message_id"] == 2


def test_no_internet_is_a_relay_error_not_a_crash(the_hub):
    with pytest.raises(relay.RelayError, match="can't reach Telegram"):
        relay.poll_once(the_hub, "TOKEN", {}, "http://127.0.0.1:9", wait=0)


def test_state_json_names_the_bot_only_while_the_relay_runs():
    assert "relay" not in hub.with_relay({"nodes": []}, "")
    assert hub.with_relay({"nodes": []}, "casio_ledger_bot")["relay"] == {"bot": "casio_ledger_bot"}


# --- the board -------------------------------------------------------------------------------

HARNESS = """
globalThis.document = { createElement: () => ({}) };
const { relayMessages } = await import("./components/relay.js");
const write = (n) => ({ command: "move", body: { id: `id-${n}`, item: `BAT-${n}`, to: "van",
                                                 note: "x".repeat(400) } });
const few = relayMessages([write(1), write(2)]);
const many = relayMessages(Array.from({ length: 20 }, (_, n) => write(n)));
const lines = few[0].split("\\n");
console.log(JSON.stringify({ few: few.length, first: lines[0], json: JSON.parse(lines[1].slice(4)),
                             many: many.length, longest: Math.max(...many.map((m) => m.length)),
                             all: many.join("").split("#fl ").length - 1 }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_board_packs_waiting_writes_into_messages_telegram_takes():
    out = subprocess.run(["node", "--input-type=module", "-e", HARNESS], cwd=hub.WEB_DIR,
                         capture_output=True, text=True, check=True, timeout=10)
    result = json.loads(out.stdout)
    assert result["few"] == 1 and result["first"] == "BAT-1 → van"
    assert result["json"]["body"]["id"] == "id-1"
    assert result["many"] > 1 and result["longest"] <= 3500 and result["all"] == 20
