"""The event-file store: files in the ledger's own Git repo are the record."""

from datetime import datetime, timezone

from field_ledger.cli import main
from field_ledger.git_source import run_git
from field_ledger.ledger import store
from field_ledger.ledger.model import Event


def event(n: int, **kw) -> Event:
    fields = dict(id=f"e{n}", ts=datetime(2026, 10, 17, 3, n, tzinfo=timezone.utc),
                  device="dev1", seq=n, actor="teyr", kind="MOVE", item="BAT-01",
                  src="truck", dst="site-b")
    return Event(**{**fields, **kw})


def test_round_trip(tmp_path):
    store.init_ledger(tmp_path)
    written = [event(1), event(2, item="CAM-01", dst="van", flags=("unconfirmed-import",))]
    for e in written:
        assert store.write_event(tmp_path, e) is True
    assert sorted(store.read_events(tmp_path), key=lambda e: e.id) == written


def test_write_is_idempotent(tmp_path):
    store.init_ledger(tmp_path)
    assert store.write_event(tmp_path, event(1)) is True
    assert store.write_event(tmp_path, event(1)) is False
    assert len(store.read_events(tmp_path)) == 1


def test_write_never_rewrites_an_existing_file(tmp_path):
    """Append-only: a second event re-using an id cannot overwrite the first."""
    store.init_ledger(tmp_path)
    store.write_event(tmp_path, event(1))
    store.write_event(tmp_path, event(1, dst="lost"))
    assert store.read_events(tmp_path)[0].dst == "site-b"


def test_each_event_is_committed(tmp_path):
    store.init_ledger(tmp_path)
    store.write_event(tmp_path, event(1))
    assert run_git(tmp_path, "status", "--porcelain") == ""


def test_init_twice_changes_nothing(tmp_path):
    ledger = tmp_path / "ledger"
    assert store.init_ledger(ledger) is True
    store.write_event(ledger, event(1))
    assert store.init_ledger(ledger) is False
    assert (ledger / ".git").is_dir()
    assert store.read_events(ledger) == [event(1)]


def test_cli_init(tmp_path, capsys):
    ledger = tmp_path / "ledger"
    main(["init", "--ledger-dir", str(ledger)])
    assert (ledger / ".git").is_dir()
    assert "created" in capsys.readouterr().out
    main(["init", "--ledger-dir", str(ledger)])
    assert "already there" in capsys.readouterr().out
