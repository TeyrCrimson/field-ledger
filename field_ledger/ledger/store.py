"""SQLite persistence. Append-only: there is no UPDATE or DELETE on events anywhere.

Event ids are UUIDs, so merging two databases is a plain INSERT OR IGNORE and running
it twice is harmless.
"""

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from .model import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    id     TEXT PRIMARY KEY,
    ts     TEXT NOT NULL,
    device TEXT NOT NULL,
    seq    INTEGER NOT NULL,
    actor  TEXT NOT NULL,
    kind   TEXT NOT NULL,
    item   TEXT NOT NULL DEFAULT '',
    src    TEXT NOT NULL DEFAULT '',
    dst    TEXT NOT NULL DEFAULT '',
    ref    TEXT NOT NULL DEFAULT '',
    note   TEXT NOT NULL DEFAULT '',
    flags  TEXT NOT NULL DEFAULT ''
);
-- Import lines that were read but wrote no event (duplicates). Recorded so that
-- re-importing the same file never re-evaluates them against newer state.
CREATE TABLE IF NOT EXISTS skipped_imports (id TEXT PRIMARY KEY);
"""
COLUMNS = ("id", "ts", "device", "seq", "actor", "kind", "item", "src", "dst", "ref", "note", "flags")


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


# --- meta ----------------------------------------------------------------------

def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
    conn.commit()


def ensure_device(conn: sqlite3.Connection) -> str:
    """This database's device id, created once and never changed."""
    device = get_meta(conn, "device")
    if device is None:
        device = uuid.uuid4().hex[:8]
        set_meta(conn, "device", device)
    return device


# --- events --------------------------------------------------------------------

def to_row(event: Event) -> tuple:
    return (event.id, event.ts.isoformat(), event.device, event.seq, event.actor, event.kind,
            event.item, event.src, event.dst, event.ref, event.note, ",".join(event.flags))


def from_row(row: tuple) -> Event:
    values = dict(zip(COLUMNS, row))
    values["ts"] = datetime.fromisoformat(values["ts"])
    values["flags"] = tuple(f for f in values["flags"].split(",") if f)
    return Event(**values)


def next_seq(conn: sqlite3.Connection, device: str) -> int:
    row = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events WHERE device = ?", (device,))
    return row.fetchone()[0] + 1


def append(conn: sqlite3.Connection, event: Event) -> bool:
    """Write one event. False if that id already exists (nothing changes)."""
    marks = ", ".join("?" * len(COLUMNS))
    cur = conn.execute(f"INSERT OR IGNORE INTO events ({', '.join(COLUMNS)}) VALUES ({marks})",
                       to_row(event))
    conn.commit()
    return cur.rowcount == 1


def load(conn: sqlite3.Connection) -> list[Event]:
    return [from_row(r) for r in conn.execute(f"SELECT {', '.join(COLUMNS)} FROM events")]


def existing_ids(conn: sqlite3.Connection) -> set[str]:
    """Ids of every event plus every import line already skipped as a duplicate."""
    events = {r[0] for r in conn.execute("SELECT id FROM events")}
    skipped = {r[0] for r in conn.execute("SELECT id FROM skipped_imports")}
    return events | skipped


def mark_skipped(conn: sqlite3.Connection, line_id: str) -> None:
    conn.execute("INSERT OR IGNORE INTO skipped_imports (id) VALUES (?)", (line_id,))
    conn.commit()


def merge(conn: sqlite3.Connection, other: Path) -> int:
    """Copy in every event from another ledger file. Returns how many were new."""
    before = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.execute("ATTACH DATABASE ? AS other", (str(other),))
    try:
        cols = ", ".join(COLUMNS)
        conn.execute(f"INSERT OR IGNORE INTO events ({cols}) SELECT {cols} FROM other.events")
        conn.commit()
    finally:
        conn.execute("DETACH DATABASE other")
    return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] - before
