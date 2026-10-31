"""Field stage 3: phones work offline.

The phone makes each write's event id, time and seq, and queues the write while the hub is
away. The hub stamps recorded_at, logs an id once, flags a time from the future, and holds a
queued write it would refuse or ask about on Needs a look until a person settles it.
"""

import json
import urllib.request
import uuid
from datetime import timedelta

from field_ledger.ledger import store
from field_ledger.ledger.state import location_of
from field_ledger.ledger.store import read_events
from test_hub_writes import PHONE, board, post, state  # noqa: F401  (board is a fixture)


def stamped(clock, minutes=0, seq=1, **body):
    """A write as the phone sends it: its own id, its own clock, its own count."""
    when = clock() + timedelta(minutes=minutes)
    return {"id": str(uuid.uuid4()), "occurred_at": when.isoformat().replace("+00:00", "Z"),
            "seq": seq, **PHONE, **body}


def needs_look(base):
    with urllib.request.urlopen(f"{base}/state.json") as response:
        return json.loads(response.read())["needs_look"]


def event(ledger, event_id):
    return next(e for e in read_events(ledger) if e.id == event_id)


def test_the_phone_names_the_event_its_time_and_seq(board):
    base, ledger, clock = board
    body = stamped(clock, minutes=-20, seq=7, item="BAT-01", to="van")
    status, answer = post(base, "move", **body)
    assert answer["event"] == body["id"]
    e = event(ledger, body["id"])
    assert e.ts == clock() - timedelta(minutes=20) and e.recorded_at == clock()
    assert e.seq == 7 and "future" not in e.flags


def test_a_resend_is_logged_once(board):
    base, ledger, clock = board
    body = stamped(clock, item="BAT-01", to="van")
    post(base, "move", **body)
    before = len(read_events(ledger))
    status, answer = post(base, "move", **body, queued=True)
    assert answer == {"verdict": "IGNORE", "messages": ["Already logged."], "event": body["id"],
                      "readback": ""}
    assert len(read_events(ledger)) == before


def test_a_resent_add_adds_nothing_more(board):
    base, ledger, clock = board
    body = stamped(clock, prefix="CAS", count=2, at="truck", name="Pelican case")
    post(base, "add", **body)
    status, answer = post(base, "add", **body)
    assert answer["messages"] == ["Already logged."]
    assert sorted(i for i in state(ledger).items if i.startswith("CAS")) == ["CAS-01", "CAS-02"]


def test_a_resent_undo_undoes_once(board):
    base, ledger, clock = board
    post(base, "move", **stamped(clock, seq=1, item="BAT-01", to="van"))
    post(base, "move", **stamped(clock, seq=2, item="BAT-02", to="van"))
    undo = stamped(clock, seq=3)
    post(base, "undo", **undo)
    post(base, "undo", **undo)
    assert location_of(state(ledger), "BAT-01") == "van"
    assert location_of(state(ledger), "BAT-02") == "truck"


def test_a_clock_ahead_is_flagged_and_cannot_win(board):
    """Five minutes ahead is drift; more is a wrong clock. Either way the event counts from
    when it arrived, so a later move by someone else still wins."""
    base, ledger, clock = board
    near = stamped(clock, minutes=4, seq=1, item="BAT-02", to="van")
    far = stamped(clock, minutes=120, seq=2, item="BAT-01", to="van")
    post(base, "move", **near)
    post(base, "move", **far)
    assert "future" not in event(ledger, near["id"]).flags
    assert "future" in event(ledger, far["id"]).flags
    clock.advance(minutes=1)
    post(base, "move", item="BAT-01", to="site-b", actor="Yoeng", device="phone-other")
    assert location_of(state(ledger), "BAT-01") == "site-b"


def test_undo_counts_from_arrival(board):
    """A move that waited 20 minutes in the queue can be undone when it lands."""
    base, ledger, clock = board
    post(base, "move", **stamped(clock, minutes=-20, item="BAT-01", to="van"), queued=True)
    status, answer = post(base, "undo", **stamped(clock, seq=2))
    assert answer["verdict"] == "ACCEPT"
    assert location_of(state(ledger), "BAT-01") == "truck"


def test_a_queued_refusal_is_held_never_dropped(board):
    base, ledger, clock = board
    body = stamped(clock, item="BAT-99", to="van")
    before = len(read_events(ledger))
    status, answer = post(base, "move", **body, queued=True)
    assert status == 200 and answer["held"] and answer["verdict"] == "REJECT"
    assert len(read_events(ledger)) == before
    [held] = needs_look(base)
    assert held["id"] == body["id"] and held["command"] == "move"
    assert held["body"]["item"] == "BAT-99" and held["messages"] == answer["messages"]
    status, again = post(base, "move", **body, queued=True)       # the answer got lost
    assert again["held"] and len(needs_look(base)) == 1


def test_a_live_refusal_is_answered_not_held(board):
    base, ledger, clock = board
    status, answer = post(base, "move", **stamped(clock, item="BAT-99", to="van"))
    assert answer["verdict"] == "REJECT" and "held" not in answer
    assert needs_look(base) == []


def test_someone_not_on_the_list_is_held_too(board):
    """A queued write has no one to tell it was malformed, so even that waits for a person."""
    base, ledger, clock = board
    status, answer = post(base, "move", **{**stamped(clock, item="BAT-01", to="van"),
                                           "actor": "Ghost"}, queued=True)
    assert status == 200 and answer["held"]
    assert "isn't in the People list" in needs_look(base)[0]["messages"][0]


def test_a_held_question_is_logged_as_the_phone_sent_it(board):
    base, ledger, clock = board
    clock.advance(hours=1)                                  # teyr is on the list: the owner                                  # the kit was added at the start
    body = stamped(clock, minutes=-30, seq=4, item="BAT-01", to="Blk 12")
    status, held = post(base, "move", **body, queued=True)
    assert held["held"] and held["verdict"] == "CONFIRM"
    clock.advance(minutes=5)
    status, answer = post(base, "settle", id=body["id"], how="log", actor="teyr", device="laptop")
    assert answer["event"] == body["id"]
    e = event(ledger, body["id"])
    assert (e.actor, e.device, e.seq, e.ts) == ("Yoeng", "phone-a1b2", 4,
                                                clock() - timedelta(minutes=35))
    assert "confirmed" in e.flags and location_of(state(ledger), "BAT-01") == "blk 12"
    assert needs_look(base) == []
    assert store.read_held(ledger, body["id"])["settled"] == {
        "by": "teyr", "at": clock().isoformat(), "how": "logged"}


def test_a_late_settled_write_keeps_its_place_in_the_phones_order(board):
    """Held at seq 1, then the phone moved the item again at seq 2: logging the held one
    later must not make it the latest."""
    base, ledger, clock = board
    post(base, "move", **stamped(clock, seq=1, item="BAT-01", to="Blk 12"), queued=True)
    held_id = needs_look(base)[0]["id"]
    clock.advance(minutes=1)
    post(base, "move", **stamped(clock, seq=2, item="BAT-01", to="van"))
    clock.advance(minutes=30)
    post(base, "settle", id=held_id, how="log", **PHONE)
    assert location_of(state(ledger), "BAT-01") == "van"


def test_logging_a_held_refusal_still_refuses(board):
    base, ledger, clock = board
    body = stamped(clock, item="BAT-99", to="van")
    post(base, "move", **body, queued=True)
    status, answer = post(base, "settle", id=body["id"], how="log", **PHONE)
    assert answer["verdict"] == "REJECT" and not answer["event"]
    assert [h["id"] for h in needs_look(base)] == [body["id"]]


def test_dismissing_logs_nothing_and_keeps_the_record(board):
    base, ledger, clock = board
    body = stamped(clock, item="BAT-99", to="van")
    post(base, "move", **body, queued=True)
    before = len(read_events(ledger))
    status, answer = post(base, "settle", id=body["id"], how="dismiss", **PHONE)
    assert answer["readback"] == "Dismissed." and len(read_events(ledger)) == before
    assert needs_look(base) == []
    assert store.read_held(ledger, body["id"])["settled"]["how"] == "dismissed"
    status, again = post(base, "settle", id=body["id"], how="dismiss", **PHONE)
    assert status == 400


def test_ids_and_times_from_a_phone_are_checked(board):
    base, ledger, clock = board
    move = {"item": "BAT-01", "to": "van", **PHONE}
    assert post(base, "move", **move, id="../../x")[0] == 400       # it becomes a file name
    assert post(base, "move", **move, queued=True)[0] == 400        # a queued write needs one
    assert post(base, "move", **move, occurred_at="2026-10-17T03:00:00")[0] == 400  # no zone
    assert post(base, "move", **move, seq=0)[0] == 400


def test_an_event_from_before_f3_has_no_recorded_at(tmp_path):
    old = {"id": "e1", "ts": "2026-10-17T03:00:00+00:00", "device": "d", "seq": 1,
           "actor": "teyr", "kind": "ADD", "item": "BAT-01", "src": "", "dst": "truck",
           "ref": "", "note": "Battery", "sha": "", "batch": "", "time_source": "", "flags": []}
    e = store.from_json(json.dumps(old))
    assert e.recorded_at is None
    conn = store.connect(tmp_path / "c.db")
    store.cache(conn, [e])
    assert store.load(conn) == [e]


def test_a_phones_batch_uses_one_of_its_seqs(board):
    """The phone counts a write once, however many events the hub makes of it. Numbering a
    3-case add 1, 2, 3 made the phone's next write (seq 2) sort before the last case's ADD:
    a day-old ADD won over today's move, and undo reached for it (2026-10-31)."""
    base, ledger, clock = board
    post(base, "add", **stamped(clock, seq=1, prefix="CAS", count=3, at="truck", name="Pelican"))
    clock.advance(minutes=24 * 60)
    post(base, "move", **stamped(clock, seq=2, item="CAS-03", to="van"))
    assert location_of(state(ledger), "CAS-03") == "van"
    clock.advance(minutes=1)
    status, answer = post(base, "undo", **stamped(clock, seq=3))
    assert answer["verdict"] == "ACCEPT"
    assert location_of(state(ledger), "CAS-03") == "truck"
