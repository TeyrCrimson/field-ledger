"""`fl add --serial`: the camera registry's join key, set once on the item's ADD event."""

import json

from field_ledger.ledger import service, store
from field_ledger.ledger.cli import main
from field_ledger.ledger.kit import Group, plan_more, plan_serial, serial_problem
from field_ledger.ledger.model import Void
from field_ledger.ledger.state import State, fold, serial_holder
from ledger_helpers import Clock, make_ctx


def fl(db, *argv):
    return main(["--db", str(db), "--ledger-dir", str(db.parent / "ledger"), *argv],
                ask=lambda _: False, now=Clock())


def setup(tmp_path):
    db = tmp_path / "l.db"
    assert fl(db, "init", "teyr") == 0
    return db


def add_events(db):
    return [e for e in store.read_events(db.parent / "ledger") if e.kind == "ADD"]


# --- CLI: the pass condition --------------------------------------------------------

def test_add_with_serial_records_it_on_the_add_event(tmp_path):
    db = setup(tmp_path)
    assert fl(db, "add", "CAM", "1", "--at", "hq", "--serial", "SN-0042") == 0
    [event] = add_events(db)
    assert (event.item, event.serial) == ("CAM-01", "SN-0042")


def test_add_without_serial_leaves_it_empty(tmp_path):
    db = setup(tmp_path)
    assert fl(db, "add", "CAM", "2", "--at", "hq") == 0
    assert [e.serial for e in add_events(db)] == ["", ""]


def test_where_shows_the_serial(tmp_path, capsys):
    db = setup(tmp_path)
    fl(db, "add", "CAM", "1", "--at", "hq", "--serial", "SN-0042")
    capsys.readouterr()
    assert fl(db, "where", "CAM-01") == 0
    out = capsys.readouterr().out
    assert out.startswith("CAM-01: hq · sn SN-0042")
    assert "sn SN-0042" in out.splitlines()[1]           # the ADD in `last:` shows it too


def test_where_without_serial_says_nothing_about_one(tmp_path, capsys):
    db = setup(tmp_path)
    fl(db, "add", "CAM", "1", "--at", "hq")
    capsys.readouterr()
    fl(db, "where", "CAM-01")
    assert "sn" not in capsys.readouterr().out


def test_serial_with_count_above_one_is_refused(tmp_path, capsys):
    db = setup(tmp_path)
    assert fl(db, "add", "CAM", "2", "--at", "hq", "--serial", "SN-1") == 1
    assert "add 1, not 2" in capsys.readouterr().out
    assert add_events(db) == []


def test_serial_already_on_another_item_is_refused(tmp_path, capsys):
    db = setup(tmp_path)
    fl(db, "add", "CAM", "1", "--at", "hq", "--serial", "SN-1")
    capsys.readouterr()
    assert fl(db, "add", "CAM", "1", "--at", "hq", "--serial", " sn-1 ") == 1
    assert "already on CAM-01" in capsys.readouterr().out
    assert len(add_events(db)) == 1


# --- pure core -----------------------------------------------------------------------

def test_serial_problem_rules():
    state = State(serials={"CAM-01": "SN-1"})
    one = Group("CAM", "Camera", 1, "hq")
    assert serial_problem(one, "SN-2", state) == ""
    assert serial_problem(one, "  ", state) == "The serial is empty."
    assert "add 1, not 3" in serial_problem(Group("CAM", "Camera", 3, "hq"), "SN-2", state)
    assert "already on CAM-01" in serial_problem(one, "sn-1", state)


def test_plan_serial_is_plan_more_plus_the_serial():
    state, group = State(items={"CAM-01": "Camera"}), Group("CAM", "Camera", 1, "hq")
    [planned] = plan_serial(group, " SN-9 ", state)
    assert planned.item == plan_more(group, state)[0].item == "CAM-02"
    assert planned.serial == "SN-9"


# --- storage and replay ------------------------------------------------------------

def test_serial_survives_a_cache_rebuild(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    group = Group("CAM", "Camera", 1, "hq")
    service.add_items(ctx, plan_serial(group, "SN-7", service.current_state(ctx)))
    conn = store.connect(tmp_path / "rebuilt.db")       # an empty cache, refilled from the record
    store.sync(conn, ctx.ledger_dir)
    assert fold(store.load(conn)).serials == {"CAM-01": "SN-7"}


def test_event_files_without_a_serial_keep_their_old_shape(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    service.add_items(ctx, plan_more(Group("BAT", "Battery", 1, "hq"), service.current_state(ctx)))
    [event] = [e for e in store.read_events(ctx.ledger_dir) if e.kind == "ADD"]
    data = json.loads(store.event_file(ctx.ledger_dir, event.id).read_text())
    assert "serial" not in data                          # older readers see nothing new
    assert store.from_json(json.dumps(data)).serial == ""


def test_voiding_the_add_frees_the_serial(tmp_path):
    ctx = make_ctx(tmp_path / "l.db")
    group = Group("CAM", "Camera", 1, "hq")
    [added] = service.add_items(ctx, plan_serial(group, "SN-3", service.current_state(ctx)))
    service.submit_void(ctx, Void(added.id, "wrong serial"))
    state = service.current_state(ctx)
    assert state.serials == {} and serial_holder(state, "SN-3") == ""
