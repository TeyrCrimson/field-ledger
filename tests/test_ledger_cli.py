"""The CLI end to end: exit codes and the confirm prompt."""

from field_ledger.ledger.cli import main
from ledger_helpers import Clock


def fl(db, *argv, ask=lambda _: False, clock=None):
    return main(["--db", str(db), *argv], ask=ask, now=clock or Clock())


def setup(tmp_path):
    db = tmp_path / "l.db"
    kit = tmp_path / "kit.csv"
    kit.write_text("prefix,name,count,location\nBAT,Battery,3,truck\n")
    assert fl(db, "init", "teyr") == 0
    assert fl(db, "kit", str(kit)) == 0
    return db


def test_move_then_where(tmp_path, capsys):
    db = setup(tmp_path)
    assert fl(db, "move", "bat1", "site", "b", "--from", "truck") == 0
    capsys.readouterr()
    assert fl(db, "where", "BAT-01") == 0
    assert capsys.readouterr().out.startswith("BAT-01: site b")


def test_reject_exits_1(tmp_path):
    db = setup(tmp_path)
    assert fl(db, "move", "BAT-99", "site-b") == 1


def test_declined_confirmation_exits_2_and_writes_nothing(tmp_path, capsys):
    db = setup(tmp_path)
    assert fl(db, "move", "BAT-01", "truck", ask=lambda _: False) == 2
    assert "Not logged." in capsys.readouterr().out
    assert fl(db, "flags") == 0
    assert "Nothing to show." in capsys.readouterr().out


def test_accepted_confirmation_writes_flagged_event(tmp_path, capsys):
    db = setup(tmp_path)
    assert fl(db, "move", "BAT-01", "truck", ask=lambda _: True) == 0
    capsys.readouterr()
    fl(db, "flags")
    assert "same-place" in capsys.readouterr().out


def test_kit_is_rerunnable(tmp_path, capsys):
    db = setup(tmp_path)
    capsys.readouterr()
    fl(db, "kit", str(tmp_path / "kit.csv"))
    assert "0 item(s) added." in capsys.readouterr().out


def test_no_name_set_stops_with_message(tmp_path):
    import pytest
    with pytest.raises(SystemExit, match="fl init"):
        fl(tmp_path / "fresh.db", "log")
