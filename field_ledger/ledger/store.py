"""Persistence. Append-only: there is no UPDATE or DELETE on events anywhere.

Two layers. The event files at the bottom of this module are the record: one JSON
file per event in the ledger's own Git repo. The SQLite tables are a cache that can
be rebuilt from them. Event ids are UUIDs, so neither layer can collide: merging two
databases is a plain INSERT OR IGNORE, and merging two ledgers is a `git pull`.
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from ..git_source import run_git
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


# --- event files: the record ---------------------------------------------------
#
# The ledger is its own Git repo, nested inside a gitignored folder so that ledger
# data can never reach this public repo. One file per event: a new file is never a
# merge conflict, which is what makes two people logging offline a non-event.

DEFAULT_LEDGER_DIR = Path("ledger")
EVENTS_DIR = "events"


def events_dir(ledger_dir: Path) -> Path:
    return ledger_dir / EVENTS_DIR


def init_ledger(ledger_dir: Path) -> bool:
    """Create the ledger's own Git repo. False if it was already there.

    Running it twice is a no-op: nothing already on disk is touched.
    """
    events_dir(ledger_dir).mkdir(parents=True, exist_ok=True)
    if (ledger_dir / ".git").exists():
        return False
    run_git(ledger_dir, "init", "-q", "-b", "main")
    # The repo commits under its own identity: a site laptop with no global git
    # config, or with commit signing on, must still be able to record a move.
    run_git(ledger_dir, "config", "user.name", "field-ledger")
    run_git(ledger_dir, "config", "user.email", "field-ledger@localhost")
    run_git(ledger_dir, "config", "commit.gpgsign", "false")
    (ledger_dir / ".gitignore").write_text("*.db\n*.sqlite\n", encoding="utf-8")
    run_git(ledger_dir, "add", "-A")
    run_git(ledger_dir, "commit", "-q", "-m", "init ledger")
    return True


def to_json(event: Event) -> str:
    data = dict(zip(COLUMNS, to_row(event)))
    data["flags"] = list(event.flags)        # a list, not the DB's comma string
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def from_json(text: str) -> Event:
    data = json.loads(text)
    data["ts"] = datetime.fromisoformat(data["ts"])
    data["flags"] = tuple(data["flags"])
    return Event(**data)


def event_file(ledger_dir: Path, event_id: str) -> Path:
    return events_dir(ledger_dir) / f"{event_id}.json"


def write_event(ledger_dir: Path, event: Event) -> bool:
    """Write and commit one event file. False if that id is already on disk.

    An existing file is never rewritten, so replaying an import or re-syncing the
    same event changes nothing. That is the append-only rule, enforced in one place.
    """
    path = event_file(ledger_dir, event.id)
    if path.exists():
        return False
    path.write_text(to_json(event), encoding="utf-8")
    run_git(ledger_dir, "add", "--", str(path.relative_to(ledger_dir)))
    run_git(ledger_dir, "commit", "-q", "-m", f"{event.kind} {event.item or event.ref}".strip())
    return True


def read_events(ledger_dir: Path) -> list[Event]:
    """Every event on disk. Read order does not matter: `state.fold` sorts."""
    return [from_json(p.read_text(encoding="utf-8"))
            for p in sorted(events_dir(ledger_dir).glob("*.json"))]
