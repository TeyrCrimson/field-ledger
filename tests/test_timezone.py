"""The ledger's `timezone` (Teyr, 2026-11-01): the audit's day and a time typed to the bot are
read in the site's zone, not whatever the hub laptop is set to. A hub left on UTC put both
8 hours off in Singapore. Unset, the machine's own zone is used, as before."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from field_ledger import hub, relay
from field_ledger.ledger import store
from field_ledger.ledger.cli import main as fl
from ledger_helpers import Clock, make_ctx, seed

SGT = ZoneInfo("Asia/Singapore")


def test_fl_set_timezone_keeps_the_name_and_refuses_one_it_does_not_know(tmp_path, capsys):
    run = lambda *argv: fl(["--db", str(tmp_path / "l.db"), "--ledger-dir", str(tmp_path / "ledger"),
                            *argv], now=Clock())
    assert run("init", "teyr") == 0
    assert run("set", "timezone", "Asia/Singapore") == 0
    assert "timezone: Asia/Singapore" in capsys.readouterr().out          # case kept
    assert store.read_settings(tmp_path / "ledger")["timezone"] == "Asia/Singapore"
    assert run("set", "timezone", "Mars/Olympus") == 1
    assert "No timezone 'Mars/Olympus' here" in capsys.readouterr().out
    assert store.read_settings(tmp_path / "ledger")["timezone"] == "Asia/Singapore"


def test_the_audit_day_starts_at_midnight_in_the_ledgers_zone(tmp_path):
    """Kit added at 11:00 SGT (03:00 UTC) on the 17th. At 01:00 SGT on the 18th it's a new
    day in Singapore, so it's due; on a hub reading UTC it's still the 17th, so it isn't."""
    ctx = make_ctx(tmp_path / "l.db")
    seed(ctx)
    now = datetime(2026, 10, 17, 17, 0, tzinfo=timezone.utc)
    for name, since, due in [("UTC", "2026-10-17T00:00:00+00:00", 0),
                             ("Asia/Singapore", "2026-10-18T00:00:00+08:00", 4)]:
        store.write_setting(ctx.ledger_dir, "timezone", name)
        audit = hub.board_state(ctx.ledger_dir, now)["audit"]
        assert (audit["since"], len(audit["due"])) == (since, due)


def test_a_typed_clock_time_is_read_in_the_ledgers_zone():
    sent = datetime(2026, 10, 17, 7, 0, tzinfo=timezone.utc)                # 15:00 in Singapore
    assert relay.asked_time("14:30", sent, SGT) == datetime(2026, 10, 17, 6, 30, tzinfo=timezone.utc)
    assert relay.asked_time("14:30", sent, timezone.utc) == datetime(2026, 10, 16, 14, 30,
                                                                     tzinfo=timezone.utc)  # day before
