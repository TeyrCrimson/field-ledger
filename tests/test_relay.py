"""F4.5 the Telegram relay: phones that can't reach the hub send their waiting writes through
the team's bot, and the hub fetches them over outbound HTTPS. A typed move gets asked for a
time (a clock time is marked `prompted`; `now` is exact); WHERE and AT are answered. Only
linked people get anything back.
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
from field_ledger.ledger import service, store
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
    assert relay.handle(the_hub, stranger, {}).startswith("BAT-01: truck\n")


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
    local = datetime(2026, 10, 17, 2, 50, tzinfo=timezone.utc).astimezone()   # 10 min before sending
    reply = relay.handle(the_hub, message(f"{local:%H:%M}", message_id=2), pending)
    assert reply == "✓ BAT-02 · Battery · was in truck → site-b" and pending == {}
    e = next(e for e in events(the_hub) if e.item == "BAT-02" and e.kind == "MOVE")
    assert (e.actor, e.device, e.time_source) == ("Yoeng", f"telegram-{YOENG}", "prompted")
    assert e.ts == datetime(2026, 10, 17, 2, 50, tzinfo=timezone.utc)


@pytest.mark.parametrize("first, second", [("MOVE BAT-02 > site-b", "now"),
                                           ("MOVE BAT-02 > site-b now", None),
                                           ("MOVE BAT-02 > site-b @now", None)])
def test_now_is_exact_so_two_of_your_own_moves_are_put_in_order(the_hub, first, second):
    """`now` is when the message was sent, not a guess (Teyr, 2026-11-01): it isn't marked
    prompted, so your next typed move of the same item isn't a ⚠ with it."""
    pending = {}
    relay.handle(the_hub, message(first), pending)
    if second:
        relay.handle(the_hub, message(second, message_id=2), pending)
    later = datetime(2026, 10, 17, 3, 10, tzinfo=timezone.utc)
    relay.handle(the_hub, message("MOVE BAT-02 > van now", message_id=3, sent=later), pending)
    state = fold(events(the_hub))
    assert [e.time_source for e in state.events if e.item == "BAT-02" and e.kind == "MOVE"] == ["", ""]
    assert location_of(state, "BAT-02") == "van" and service.open_conflicts(state) == {}


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


def test_where_names_the_chain_and_who_put_each_link_there(the_hub):
    """"I know it's in Case A, but who shifted Case A?" (Teyr, 2026-11-02)."""
    sent = datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)
    add = lambda *argv: fl(["--ledger-dir", str(the_hub.ledger_dir), "--db", str(the_hub.db),
                            "--actor", "teyr", *argv], now=lambda: sent)
    assert add("add", "CAS", "1", "--at", "truck", "--container") == 0
    relay.handle(the_hub, message("MOVE BAT-01 > CAS-01 now", sent=sent), {})
    reply = relay.handle(the_hub, message("WHERE BAT-01", message_id=2, sent=sent), {})
    at = f"{sent.astimezone():%H:%M}"                                          # today: no date
    assert reply == f"BAT-01: CAS-01 at truck\nPut there: BAT-01 by Yoeng, {at} · CAS-01 by teyr, {at}"


@pytest.mark.parametrize("typed, read", [
    ("/move BAT-01 > van now", "MOVE BAT-01 > van now"), ("/where@casio_ledger_bot BAT-01", "WHERE BAT-01"),
    ("/AT van", "AT van"), ("/start abc", "/start abc"), ("/moved", "/moved")])
def test_the_menus_slash_forms_read_as_the_words(typed, read):
    assert relay.unslash(typed) == read


def test_a_bare_command_from_the_menu_gets_an_example(the_hub):
    assert relay.handle(the_hub, message("/move"), {}) == "Send it like this: MOVE BAT-12 > van now"


@pytest.mark.parametrize("line, meant", [
    ("MVOE BAT-01 > site-b", "MOVE BAT-01 > site-b"),      # the command word
    ("WHERE BTA-01", "WHERE BAT-01"),                      # an item
    ("MOVE BAT-01 > trck", "MOVE BAT-01 > truck"),         # a place nobody uses, close to one in use
    ("move bat-1 > site-b", None),                         # nothing wrong: case and padding are fine
    ("MOVE BAT-01 > DRN-03", None),                        # ID-shaped: the hub already asks
    ("MOVE BAT-01 > warehouse", None),                     # new, and close to nothing
    ("AT site-b", None),
])
def test_did_you_mean(the_hub, line, meant):
    assert relay.did_you_mean(line, fold(events(the_hub))) == meant


def test_yes_sends_the_suggestion_and_keeps_the_time(the_hub):
    pending = {}
    reply = relay.handle(the_hub, message("MOVE BAT-01 > site-v now"), pending)
    assert reply.startswith("Did you mean: MOVE BAT-01 > site-b now\n")
    assert relay.handle(the_hub, message("yes", message_id=2), pending).startswith("✓ BAT-01")
    assert location_of(fold(events(the_hub)), "BAT-01") == "site-b" and pending == {}


def test_sending_yours_again_keeps_it_as_typed(the_hub):
    """site-c may really be new: one resend says so, and it's logged as typed."""
    pending = {}
    assert relay.handle(the_hub, message("MOVE BAT-02 > site-c now"), pending).startswith("Did you mean")
    assert relay.handle(the_hub, message("MOVE BAT-02 > site-c now", message_id=2), pending).startswith("✓ BAT-02")
    assert location_of(fold(events(the_hub)), "BAT-02") == "site-c"


def test_questions_and_everything_else(the_hub):
    assert relay.handle(the_hub, message("where bat-1"), {}).startswith("BAT-01: truck\n")
    assert relay.handle(the_hub, message("AT site-b"), {}) == "At site-b: CAM-01"
    assert relay.handle(the_hub, message("RENAME truck > lorry"), {}).startswith("Only moves come through")
    assert relay.handle(the_hub, message("hello"), {}).startswith("unknown command 'HELLO'")


# --- polling a (fake) Telegram -------------------------------------------------------------

class FakeTelegram(BaseHTTPRequestHandler):
    updates: list = []
    sent: list = []
    offsets: list = []
    calls: list = []

    def do_POST(self):
        method = self.path.rsplit("/", 1)[1]
        params = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.calls.append((method, params))
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
    assert [s["text"].split("\n")[0] for s in FakeTelegram.sent] == [
        "BAT-01: truck", "✓ BAT-01 · Battery · was in truck → van"]
    assert FakeTelegram.sent[1]["reply_to_message_id"] == 2


def test_starting_registers_the_command_menu(the_hub):
    """Typing / in the chat lists /move, /where and /at: the only as-you-type help a bot can
    give, since it sees nothing until a message is sent (Teyr, 2026-11-02)."""
    FakeTelegram.updates, FakeTelegram.calls = [], []
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeTelegram)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stop = relay.start(the_hub, "TOKEN", f"http://127.0.0.1:{server.server_address[1]}")
    try:
        for _ in range(100):
            if any(method == "setMyCommands" for method, _ in FakeTelegram.calls):
                break
            threading.Event().wait(0.02)
    finally:
        stop.set()
        server.shutdown()
    commands = next(p for m, p in FakeTelegram.calls if m == "setMyCommands")["commands"]
    assert [c["command"] for c in commands] == ["move", "where", "at"]


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
