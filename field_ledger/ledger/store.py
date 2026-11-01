"""Persistence. Append-only: there is no UPDATE or DELETE on events anywhere.

Two layers. The event files at the bottom of this module are the record: one JSON
file per event in the ledger's own Git repo. The SQLite tables are a cache that can
be rebuilt from them. Event ids are UUIDs, so neither layer can collide: merging two
databases is a plain INSERT OR IGNORE, and merging two ledgers is a `git pull`.
"""

import json
import secrets
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
    sha    TEXT NOT NULL DEFAULT '',
    batch  TEXT NOT NULL DEFAULT '',
    time_source TEXT NOT NULL DEFAULT '',
    flags  TEXT NOT NULL DEFAULT '',
    recorded_at TEXT NOT NULL DEFAULT ''
);
"""
COLUMNS = ("id", "ts", "device", "seq", "actor", "kind", "item", "src", "dst", "ref", "note",
           "sha", "batch", "time_source", "flags", "recorded_at")


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    present = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
    for column in COLUMNS:          # a cache written by an older version: add what it lacks
        if column not in present:
            conn.execute(f"ALTER TABLE events ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
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

def when(text: str) -> datetime | None:
    """An optional time: events from before F3 have no recorded_at."""
    return datetime.fromisoformat(text) if text else None


def to_row(event: Event) -> tuple:
    return (event.id, event.ts.isoformat(), event.device, event.seq, event.actor, event.kind,
            event.item, event.src, event.dst, event.ref, event.note, event.sha, event.batch,
            event.time_source,
            ",".join(event.flags), event.recorded_at.isoformat() if event.recorded_at else "")


def from_row(row: tuple) -> Event:
    values = dict(zip(COLUMNS, row))
    values["ts"] = datetime.fromisoformat(values["ts"])
    values["flags"] = tuple(f for f in values["flags"].split(",") if f)
    values["recorded_at"] = when(values["recorded_at"])
    return Event(**values)


def next_seq(conn: sqlite3.Connection, device: str) -> int:
    row = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM events WHERE device = ?", (device,))
    return row.fetchone()[0] + 1


def cache(conn: sqlite3.Connection, events: list[Event]) -> None:
    """Copy events into the cache. Ids already cached are left alone."""
    marks = ", ".join("?" * len(COLUMNS))
    conn.executemany(f"INSERT OR IGNORE INTO events ({', '.join(COLUMNS)}) VALUES ({marks})",
                     [to_row(e) for e in events])
    conn.commit()


def load(conn: sqlite3.Connection) -> list[Event]:
    return [from_row(r) for r in conn.execute(f"SELECT {', '.join(COLUMNS)} FROM events")]


def existing_ids(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT id FROM events")}


def merge(conn: sqlite3.Connection, other: Path) -> int:
    """Copy in every event from another ledger database. Returns how many were new.

    Only the cache changes here; the next `sync` writes them to the record. Between two
    ledgers that already use event files, `git pull` in the ledger repo does this job.
    """
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
SETTINGS_FILE = "settings.json"
# ponytail: one key so far; id_digits, undo_minutes etc. move here when they become settable
DEFAULT_SETTINGS = {"build_home": "hq"}


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


def stored_settings(ledger_dir: Path) -> dict:
    path = ledger_dir / SETTINGS_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def commit_settings(ledger_dir: Path, stored: dict, message: str) -> None:
    (ledger_dir / SETTINGS_FILE).write_text(json.dumps(stored, indent=2, sort_keys=True) + "\n",
                                            encoding="utf-8")
    run_git(ledger_dir, "add", "--", SETTINGS_FILE)
    run_git(ledger_dir, "commit", "-q", "-m", message)


def read_settings(ledger_dir: Path) -> dict[str, str]:
    """Ledger-wide settings. They live in the ledger repo next to the events, so every
    device that pulls the ledger deploys from the same home. A missing key is its default."""
    return {**DEFAULT_SETTINGS, **stored_settings(ledger_dir)}


def write_setting(ledger_dir: Path, key: str, value: str) -> None:
    """Set one known key and commit it. Settings are config, not events: changing one
    changes what the next command does, never what the log already says."""
    if key not in DEFAULT_SETTINGS:
        raise KeyError(key)
    commit_settings(ledger_dir, {**stored_settings(ledger_dir), key: value}, f"set {key} = {value}")


def read_containers(ledger_dir: Path) -> set[str]:
    """Kinds (3-letter prefixes) whose items can hold other things: a case, a van, a drone.
    A kind nobody has set can't: a battery is never a place to put things."""
    kinds = stored_settings(ledger_dir).get("kinds", {})
    return {prefix for prefix, kind in kinds.items() if kind.get("container")}


def set_container(ledger_dir: Path, prefix: str, container: bool) -> None:
    stored = stored_settings(ledger_dir)
    kinds = stored.get("kinds", {})
    if kinds.get(prefix, {}).get("container", False) == container:
        return
    kinds[prefix] = {**kinds.get(prefix, {}), "container": container}
    commit_settings(ledger_dir, {**stored, "kinds": kinds},
                    f"kind {prefix}: container {'yes' if container else 'no'}")


def read_kind_states(ledger_dir: Path) -> dict[str, list[str]]:
    """Each kind's own states, in the order the board shows them. A kind nobody has given
    states to has none: most kit is just where it is."""
    kinds = stored_settings(ledger_dir).get("kinds", {})
    return {prefix: list(kind["states"]) for prefix, kind in kinds.items() if kind.get("states")}


def set_kind_states(ledger_dir: Path, prefix: str, states: list[str]) -> None:
    """Replace a kind's states. Events that used a state since dropped keep it: the log
    says what was true then, and the next STATE uses the new list."""
    stored = stored_settings(ledger_dir)
    kinds = stored.get("kinds", {})
    kinds[prefix] = {**kinds.get(prefix, {}), "states": states}
    commit_settings(ledger_dir, {**stored, "kinds": kinds},
                    f"kind {prefix}: states {' / '.join(states) or 'none'}")


def read_people(ledger_dir: Path) -> list[str]:
    """The ledger's People list: the names phones pick from, so logged_by is never a typo."""
    return list(stored_settings(ledger_dir).get("people", []))


def add_person(ledger_dir: Path, name: str) -> str:
    """Add a name once (ignoring case and spacing) and return it as the list spells it.
    Someone new types their name once, when they first open the board."""
    name = " ".join(name.split())
    people = read_people(ledger_dir)
    known = next((p for p in people if p.casefold() == name.casefold()), None)
    if known:
        return known
    commit_settings(ledger_dir, {**stored_settings(ledger_dir), "people": people + [name]},
                    f"people: add {name}")
    return name


def link_code(ledger_dir: Path, name: str) -> str:
    """A one-time code that links a Telegram account to `name` on the People list. Sending it
    to the bot (`/start <code>`) is the only way in: the bot answers nobody it doesn't know."""
    code = secrets.token_hex(4)
    stored = stored_settings(ledger_dir)
    commit_settings(ledger_dir, {**stored, "telegram_codes": {**stored.get("telegram_codes", {}),
                                                              code: name}},
                    f"telegram: link code for {name}")
    return code


def use_link_code(ledger_dir: Path, code: str, user_id: str) -> str | None:
    """Link the Telegram account to the code's name and spend the code. None if no such code."""
    stored = stored_settings(ledger_dir)
    codes = dict(stored.get("telegram_codes", {}))
    name = codes.pop(code, None)
    if name is None:
        return None
    commit_settings(ledger_dir, {**stored, "telegram_codes": codes,
                                 "telegram": {**stored.get("telegram", {}), user_id: name}},
                    f"telegram: {name} linked")
    return name


def telegram_people(ledger_dir: Path) -> dict[str, str]:
    """Telegram user id -> name on the People list."""
    return dict(stored_settings(ledger_dir).get("telegram", {}))


def to_json(event: Event) -> str:
    data = dict(zip(COLUMNS, to_row(event)))
    data["flags"] = list(event.flags)        # a list, not the DB's comma string
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def from_json(text: str) -> Event:
    data = json.loads(text)
    data["ts"] = datetime.fromisoformat(data["ts"])
    data["flags"] = tuple(data["flags"])
    data["recorded_at"] = when(data.get("recorded_at", ""))
    return Event(**data)


def event_file(ledger_dir: Path, event_id: str) -> Path:
    return events_dir(ledger_dir) / f"{event_id}.json"


def write_events(ledger_dir: Path, events: list[Event]) -> list[Event]:
    """Write the event files and commit them together. Returns the ones that were new.

    An existing file is never rewritten, so replaying an import or re-syncing the
    same event changes nothing. That is the append-only rule, enforced in one place.
    """
    new = [e for e in events if not event_file(ledger_dir, e.id).exists()]
    if not new:
        return []
    for e in new:
        event_file(ledger_dir, e.id).write_text(to_json(e), encoding="utf-8")
    run_git(ledger_dir, "add", "--", EVENTS_DIR)
    one = new[0]
    message = f"{one.kind} {one.item or one.ref}".strip() if len(new) == 1 else f"{len(new)} events"
    run_git(ledger_dir, "commit", "-q", "-m", message)
    return new


def write_event(ledger_dir: Path, event: Event) -> bool:
    """Write and commit one event file. False if that id is already on disk."""
    return bool(write_events(ledger_dir, [event]))


def read_events(ledger_dir: Path) -> list[Event]:
    """Every event on disk. Read order does not matter: `state.fold` sorts."""
    return [from_json(p.read_text(encoding="utf-8"))
            for p in sorted(events_dir(ledger_dir).glob("*.json"))]


# --- needs a look: queued writes the hub wouldn't log on arrival -------------------------
#
# Not events: nothing here is in the record until a person logs it. One file per arrival,
# named by the event id it would have had, committed like an event so a dead hub loses none.
# Settling writes who settled it and how into the file, which stays: a dismissal is findable.

HELD_DIR = "needs-a-look"


def held_file(ledger_dir: Path, event_id: str) -> Path:
    return ledger_dir / HELD_DIR / f"{event_id}.json"


def read_held(ledger_dir: Path, event_id: str) -> dict | None:
    path = held_file(ledger_dir, event_id)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def needs_a_look(ledger_dir: Path) -> list[dict]:
    """Arrivals nobody has settled yet, oldest first."""
    entries = [json.loads(p.read_text(encoding="utf-8"))
               for p in (ledger_dir / HELD_DIR).glob("*.json")]
    return sorted((e for e in entries if not e.get("settled")), key=lambda e: e["recorded_at"])


def write_held(ledger_dir: Path, entry: dict, message: str) -> None:
    path = held_file(ledger_dir, entry["id"])
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(entry, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run_git(ledger_dir, "add", "--", HELD_DIR)
    run_git(ledger_dir, "commit", "-q", "-m", message)


# --- keeping the cache honest ----------------------------------------------------

def add(conn: sqlite3.Connection, ledger_dir: Path, events: list[Event]) -> None:
    """The one write path: the record first, then the cache. A crash between the two
    leaves a file the cache lacks, which the next `sync` picks up."""
    write_events(ledger_dir, events)
    cache(conn, events)


def sync(conn: sqlite3.Connection, ledger_dir: Path) -> None:
    """Make the cache and the files hold the same events.

    Files the cache lacks came from a `git pull` (or a crash mid-`add`): cache them.
    Cached events with no file predate the event files or came in through `merge`:
    write them, so the record is complete before anything is rebuilt from it.
    """
    on_disk = {p.stem for p in events_dir(ledger_dir).glob("*.json")}
    cached = load(conn)
    write_events(ledger_dir, [e for e in cached if e.id not in on_disk])
    missing = on_disk - {e.id for e in cached}
    cache(conn, [from_json(event_file(ledger_dir, i).read_text(encoding="utf-8"))
                 for i in sorted(missing)])


def rebuild(conn: sqlite3.Connection, ledger_dir: Path) -> int:
    """Throw the cached events away and reload them from the files. Returns the count.

    Device id and name stay: they are this laptop's settings, not part of the record.
    """
    events = read_events(ledger_dir)
    conn.execute("DELETE FROM events")
    cache(conn, events)
    return len(events)
