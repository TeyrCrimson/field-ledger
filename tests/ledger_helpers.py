"""Shared fixtures for ledger tests: a controllable clock and a seeded ledger."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from field_ledger.ledger import service, store
from field_ledger.ledger.kit import Group, plan_kit


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 10, 17, 3, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t += timedelta(**kw)


def make_ctx(db: Path, actor: str = "teyr", clock: Clock | None = None) -> service.Context:
    """A cache at `db` over its own ledger repo next to it (l.db -> l-ledger/)."""
    ledger = db.with_name(f"{db.stem}-ledger")
    store.init_ledger(ledger)
    conn = store.connect(db)
    store.sync(conn, ledger)
    return service.Context(conn, actor, store.ensure_device(conn), clock or Clock(), ledger)


def seed(ctx: service.Context) -> None:
    """BAT-01..03 in the truck, CAM-01 at site-b."""
    for group in (Group("BAT", "Battery", 3, "truck"), Group("CAM", "Camera", 1, "site-b")):
        service.add_items(ctx, plan_kit(group, service.current_state(ctx)))
