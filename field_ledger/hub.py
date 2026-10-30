"""The hub: serves the board to this laptop, and with `--lan` to phones on the field network.

Two kinds of request. GETs are read-only: `/state.json` (the replayed state, plus the People
list) and the static web front end (`web/`, or `--web-dir` to try a design). The front end
is plain files split into components, so a design pass replaces files and never touches
Python, and Python never writes HTML. POSTs to `/api/<command>` are the board's writes. They
go through the same service functions as `fl`, so the board accepts and refuses exactly what
the CLI does. The hub is the ledger's only committer, so writes run one at a time.

Phones work offline (field stage 3). A phone gives each write its event id, its time and its
own sequence number, and queues it while the hub is away. The hub stamps recorded_at, logs an
event id once (a resend answers "already logged"), and keeps a queued write it would refuse or
ask about on the ledger's Needs a look list until a person settles it: nobody was there to ask.

Phones open it over HTTPS too (field stage 3b), so the board can open with no hub: plain
http and HTTPS share one port, told apart by the first byte. A phone joins by scanning the QR
code on the laptop (`/phone-setup.json`), which leads to `setup.html` and the hub's own CA
(`/ca.crt`, see tls.py).

The hub binds to 127.0.0.1 unless told otherwise. There are no logins (the threat model is
honest mistakes), so the LAN is opt-in, and every write names a person from the People list
and a device.
"""

import ipaddress
import json
import re
import socket
import ssl
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import qr
from .ledger import service, store
from .ledger.ids import canonical_location, is_prefix
from .ledger.kit import Group, plan_more
from .ledger.model import Kind, Move, Verdict
from .ledger.state import State, ancestors, deployed_sha, fold, location_of
from .ledger.validate import holds_things

WEB_DIR = Path(__file__).parent / "web"
TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript",
         ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
         ".webmanifest": "application/manifest+json", ".ttf": "font/ttf", ".txt": "text/plain"}
MAX_BODY = 16 * 1024                        # a move is a few hundred bytes
DEVICE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
PEEK_SECONDS = 10                           # a client that sends nothing gives up its thread


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Hub:
    ledger_dir: Path
    web_dir: Path = WEB_DIR
    db: Path = Path("field-ledger.db")      # the cache; synced from the event files per write
    now: Callable[[], datetime] = utc_now
    lock: threading.Lock = field(default_factory=threading.Lock)
    setup_url: str = ""                     # what the laptop's QR code opens; '' without --lan
    ca_cert: Path | None = None             # the CA a phone installs; None without HTTPS
    ca_name: str = ""                       # how a phone lists that CA


class BadRequest(ValueError):
    """The request itself is wrong (not a refused move): HTTP 400."""


# --- reading -----------------------------------------------------------------------

def snapshot(state: State, open_: dict[str, tuple[str, str]], now: datetime,
             people: list[str] | None = None, needs_look: list[dict] | None = None) -> dict:
    """The replayed state in the shape the board reads. This shape is the contract
    between the hub and any front end (README "The hub"); the front end is free to change."""
    nodes = []
    for node, group in sorted(state.items.items()):
        chain = ancestors(state, node)                     # parent first, place last
        entry = {"id": node, "group": group, "fixed": node in state.fixed,
                 "parent": chain[0] if chain else "", "location": chain[-1] if chain else "",
                 "chain": chain, "container": holds_things(node, state)}
        if group == "build":
            entry |= {"sha": deployed_sha(state, node), "label": state.labels.get(node, "")}
        states = state.kind_states.get(node.split("-")[0], []) if node not in state.fixed else []
        if states and group != "build":
            entry |= {"state": state.conditions.get(node, ""), "states": states}
        if node in open_:
            entry["conflict"] = {"latest": open_[node][0], "other": open_[node][1]}
        last = state.last_event.get(node)
        if last:
            entry["last"] = {"by": last.actor, "at": last.ts.isoformat(), "event": last.id}
        nodes.append(entry)
    places = ({n["location"] for n in nodes if n["location"]}
              | {n for n in state.fixed if n not in state.where})
    return {"generated_at": now.isoformat(), "places": sorted(places), "nodes": nodes,
            "people": people or [], "needs_look": needs_look or []}


def board_state(ledger_dir: Path, now: datetime | None = None) -> dict:
    """Read the event files directly, like `show` and the stale-work board: no cache, no
    device, nothing written."""
    state = fold(store.read_events(ledger_dir))
    state.containers = store.read_containers(ledger_dir)
    state.kind_states = store.read_kind_states(ledger_dir)
    return snapshot(state, service.open_conflicts(state), now or utc_now(),
                    store.read_people(ledger_dir), store.needs_a_look(ledger_dir))


# --- writing -------------------------------------------------------------------------

def text(body: dict, key: str, required: bool = True, limit: int = 200) -> str:
    value = body.get(key, "")
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise BadRequest(f"'{key}' is missing or not text.")
    return value.strip()


def phone_id(body: dict, required: bool) -> str | None:
    """The event id the phone made for this write. A UUID, since it becomes a file name."""
    value = body.get("id")
    if value is None and not required:
        return None
    try:
        if isinstance(value, str) and str(uuid.UUID(value)) == value:
            return value
    except ValueError:
        pass
    raise BadRequest("'id' must be a lowercase UUID.")


def phone_time(body: dict) -> datetime | None:
    """occurred_at: when the person tapped, by the phone's clock."""
    value = body.get("occurred_at")
    if value is None:
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))    # 3.10 can't read Z
    except (AttributeError, ValueError):
        when = None
    if when is None or when.tzinfo is None:
        raise BadRequest("'occurred_at' must be an ISO time with a zone, e.g. 2026-10-28T14:02Z.")
    return when


def phone_seq(body: dict) -> int | None:
    value = body.get("seq")
    if value is not None and (type(value) is not int or value < 1):
        raise BadRequest("'seq' must be a whole number from 1.")
    return value


def reply(outcome: service.Outcome, readback: str = "") -> dict:
    """What every write answers: the verdict, its messages, and (if something was written)
    the readback line the board shows with its Undo."""
    return {"verdict": outcome.verdict.kind.name, "messages": list(outcome.verdict.messages),
            "event": outcome.event.id if outcome.event else None,
            "readback": readback if outcome.event else ""}


def api_move(ctx: service.Context, body: dict) -> dict:
    before = service.current_state(ctx)
    outcome = service.submit_move(ctx, Move(text(body, "item"), text(body, "to")),
                                  confirmed=body.get("confirmed") is True, event_id=body.get("id"))
    e = outcome.event
    return reply(outcome, e and (f"✓ {e.item} · {before.items.get(e.item, '')} · "
                                 f"was in {location_of(before, e.item) or '—'} → {e.dst}"))


def api_undo(ctx: service.Context, body: dict) -> dict:
    outcome = service.submit_undo(ctx, event_id=body.get("id"))
    return reply(outcome, "Undone. " + " ".join(outcome.verdict.messages))


def api_resolve(ctx: service.Context, body: dict) -> dict:
    outcome = service.submit_resolve(ctx, text(body, "item"), text(body, "to"),
                                     event_id=body.get("id"))
    e = outcome.event
    return reply(outcome, e and f"⚠ settled: {e.item} is in {e.dst}")


def api_label(ctx: service.Context, body: dict) -> dict:
    before = service.current_state(ctx)
    outcome = service.submit_label(ctx, text(body, "build"), text(body, "label"),
                                   text(body, "reason", required=False), body.get("id"))
    e = outcome.event
    return reply(outcome, e and (f"SEC {e.item} · {location_of(before, e.item) or '—'} · "
                                 f"was {before.labels.get(e.item, '—')} → {e.dst}"))


def api_state(ctx: service.Context, body: dict) -> dict:
    before = service.current_state(ctx)
    outcome = service.submit_state(ctx, text(body, "item"), text(body, "state"),
                                   text(body, "reason", required=False), body.get("id"))
    e = outcome.event
    return reply(outcome, e and (f"STATE {e.item} · {before.items.get(e.item, '')} · "
                                 f"was {before.conditions.get(e.item, '—')} → {e.dst}"))


def api_add(ctx: service.Context, body: dict) -> dict:
    """Items created in the field without the CLI: N more of a group, at a place."""
    prefix, at = text(body, "prefix"), canonical_location(text(body, "at"))
    count = body.get("count")
    if not is_prefix(prefix):
        raise BadRequest("'prefix' must be exactly 3 letters, e.g. BAT.")
    if not isinstance(count, int) or not 1 <= count <= 100:
        raise BadRequest("'count' must be a whole number from 1 to 100.")
    name = text(body, "name", required=False) or prefix.upper()
    if body.get("container") is True:
        store.set_container(ctx.ledger_dir, prefix.upper(), True)
    written = service.add_items(ctx, plan_more(Group(prefix.upper(), name, count, at),
                                               service.current_state(ctx)), body.get("id"))
    ids = f"{written[0].item}" + (f"..{written[-1].item}" if len(written) > 1 else "")
    outcome = service.Outcome(Verdict(Kind.ACCEPT), written[-1])
    return reply(outcome, f"✓ {len(written)} added: {ids} · {name} · at {at}")


WRITES = {"move": api_move, "undo": api_undo, "resolve": api_resolve, "label": api_label,
          "state": api_state, "add": api_add}


def api_people(hub: Hub, body: dict) -> dict:
    """Someone new names themselves once, on first opening the board."""
    name = store.add_person(hub.ledger_dir, text(body, "name", limit=40))
    return {"verdict": "ACCEPT", "messages": [], "event": None, "readback": f"Hello, {name}.",
            "name": name, "people": store.read_people(hub.ledger_dir)}


def person(hub: Hub, body: dict) -> str:
    actor = text(body, "actor", limit=40)
    if actor not in store.read_people(hub.ledger_dir):
        raise BadRequest(f"'{actor}' isn't in the People list. Pick your name first.")
    return actor


def run(hub: Hub, command: str, body: dict) -> dict:
    """Run one write as the person, device, time and seq the request names. A fresh cache
    connection per write: the server is threaded, and syncing first picks up `fl` and
    `git pull`."""
    actor, device = person(hub, body), text(body, "device", limit=64)
    if not DEVICE.match(device):
        raise BadRequest("'device' must be letters, digits and dashes.")
    occurred_at, seq = phone_time(body), phone_seq(body)
    conn = store.connect(hub.db)
    try:
        store.sync(conn, hub.ledger_dir)
        return WRITES[command](service.Context(conn, actor, device, hub.now, hub.ledger_dir,
                                               occurred_at=occurred_at, seq=seq), body)
    finally:
        conn.close()


def write(hub: Hub, command: str, body: dict) -> dict:
    """One request. An event id is logged once. A write that waited in a phone's queue and
    can't be logged as it stands (refused, asked, or malformed) is held, not dropped."""
    if command == "people":
        return api_people(hub, body)
    if command == "settle":
        return api_settle(hub, body)
    queued = body.get("queued") is True
    event_id = phone_id(body, required=queued)
    if event_id and store.event_file(hub.ledger_dir, event_id).exists():
        return {"verdict": "IGNORE", "messages": ["Already logged."], "event": event_id,
                "readback": ""}
    if event_id and (entry := store.read_held(hub.ledger_dir, event_id)):
        return held_reply(entry)
    try:
        answer = run(hub, command, body)
    except BadRequest as error:
        if not queued:
            raise
        answer = {"verdict": "REJECT", "messages": [str(error)], "event": None, "readback": ""}
    if queued and answer["verdict"] in ("REJECT", "CONFIRM"):
        return hold(hub, command, body, answer)
    return answer


# --- needs a look ------------------------------------------------------------------------

def held_reply(entry: dict) -> dict:
    return {"verdict": entry["verdict"], "messages": entry["messages"], "event": None,
            "readback": "", "held": True}


def hold(hub: Hub, command: str, body: dict, answer: dict) -> dict:
    entry = {"id": body["id"], "command": command,
             "body": {k: v for k, v in body.items() if k not in ("queued", "confirmed")},
             "verdict": answer["verdict"], "messages": answer["messages"],
             "recorded_at": hub.now().isoformat(), "settled": None}
    store.write_held(hub.ledger_dir, entry, f"needs a look: {command} {body['id'][:8]}")
    return held_reply(entry)


def api_settle(hub: Hub, body: dict) -> dict:
    """Anyone settles a held arrival, and their name goes on it. "log" writes it as its phone
    sent it (same person, time and seq), answering yes to any question; every other rule
    still applies, so a refusal stays on the list with its reason. "dismiss" logs nothing."""
    settler, how = person(hub, body), body.get("how")
    if how not in ("log", "dismiss"):
        raise BadRequest("'how' must be 'log' or 'dismiss'.")
    entry = store.read_held(hub.ledger_dir, phone_id(body, required=True))
    if entry is None or entry["settled"]:
        raise BadRequest("Nothing is waiting under that id.")
    if how == "log":
        answer = run(hub, entry["command"], {**entry["body"], "confirmed": True})
        if not answer["event"]:
            return answer
    else:
        answer = {"verdict": "ACCEPT", "messages": [], "event": None, "readback": "Dismissed."}
    done = "logged" if how == "log" else "dismissed"
    entry["settled"] = {"by": settler, "at": hub.now().isoformat(), "how": done}
    store.write_held(hub.ledger_dir, entry, f"needs a look: {done} {entry['id'][:8]} by {settler}")
    return answer


# --- HTTP -----------------------------------------------------------------------------

class Board(BaseHTTPRequestHandler):
    """GET for the board and its files, POST /api/<command> for writes. Any other method
    gets the server's stock 'unsupported' answer."""

    def __init__(self, *args, hub: Hub, **kwargs):
        self.hub = hub
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        path = unquote(self.path.split("?", 1)[0])
        if path == "/state.json":
            return self.send_json(HTTPStatus.OK, board_state(self.hub.ledger_dir, self.hub.now()))
        if path == "/phone-setup.json" and self.hub.setup_url:
            return self.send_json(HTTPStatus.OK, phone_setup(self.hub))
        if path == "/ca.crt" and self.hub.ca_cert:
            return self.send(HTTPStatus.OK, "application/x-x509-ca-cert",
                             self.hub.ca_cert.read_bytes(),
                             {"Content-Disposition": 'attachment; filename="field-ledger-hub.crt"'})
        if path == "/web-files.json":
            return self.send_json(HTTPStatus.OK, web_files(self.hub.web_dir))
        root = self.hub.web_dir.resolve()
        file = (root / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
        if not file.is_relative_to(root) or not file.is_file():     # no ../ out of web/
            return self.send(HTTPStatus.NOT_FOUND, "text/plain", b"not found")
        self.send(HTTPStatus.OK, TYPES.get(file.suffix, "application/octet-stream"),
                  file.read_bytes())

    def do_POST(self) -> None:
        command = self.path.split("?", 1)[0].removeprefix("/api/")
        if command not in WRITES and command not in ("people", "settle"):
            return self.send(HTTPStatus.NOT_FOUND, "text/plain", b"not found")
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise BadRequest("Request too large.")
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise BadRequest("Send a JSON object.")
            with self.hub.lock:
                result = write(self.hub, command, body)
        except (BadRequest, json.JSONDecodeError, UnicodeDecodeError) as error:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        self.send_json(HTTPStatus.OK, result)

    def send_json(self, status: HTTPStatus, data: dict | list) -> None:
        self.send(status, TYPES[".json"], json.dumps(data, indent=1).encode())

    def send(self, status: HTTPStatus, kind: str, body: bytes,
             headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Type", f"{kind}; charset=utf-8" if kind.startswith("text")
                         else kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")    # a design swap shows on reload
        self.end_headers()
        self.wfile.write(body)


def phone_setup(hub: Hub) -> dict:
    """What the laptop's "Add a phone" shows: the setup address and its QR code, a row of
    0s and 1s per line (the front end draws it), and the CA's name for removing old ones."""
    return {"url": hub.setup_url, "ca_name": hub.ca_name,
            "qr": ["".join("1" if m else "0" for m in row) for row in qr.encode(hub.setup_url)]}


def web_files(web_dir: Path) -> list[str]:
    """Every file of the board, for the service worker to keep: whatever a design pass adds."""
    return sorted(p.relative_to(web_dir).as_posix() for p in web_dir.rglob("*") if p.is_file())


class HubServer(ThreadingHTTPServer):
    """Plain http and HTTPS on one port. A TLS connection always opens with byte 0x16, so
    the first byte says which, and the field laptop needs no second firewall rule."""

    tls: ssl.SSLContext | None = None

    def finish_request(self, request, client_address) -> None:
        if self.tls is None:
            return super().finish_request(request, client_address)
        try:
            request.settimeout(PEEK_SECONDS)
            if request.recv(1, socket.MSG_PEEK) != b"\x16":
                request.settimeout(None)
                return super().finish_request(request, client_address)
            secure = self.tls.wrap_socket(request, server_side=True)
        except OSError:          # SSLError too: a phone that doesn't trust the CA yet, or gave up
            return
        secure.settimeout(None)
        try:
            super().finish_request(secure, client_address)
        finally:
            secure.close()


def make_server(hub: Hub, host: str = "127.0.0.1", port: int = 8765,
                tls: ssl.SSLContext | None = None) -> HubServer:
    """Port 0 picks a free one (tests); `server_address` says which."""
    server = HubServer((host, port), partial(Board, hub=hub))
    server.tls = tls
    return server


def lan_address() -> str:
    """This machine's address on the network it routes through. Connecting a UDP socket
    sends nothing; it only asks the OS which interface it would use."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def behind_wsl_nat(address: str) -> bool:
    """WSL2's default networking hides it behind a 172.16/12 address that only Windows can
    reach, so a phone on the router can't open the board until it's set up (README)."""
    try:
        wsl = "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False
    return wsl and ipaddress.ip_address(address) in ipaddress.ip_network("172.16.0.0/12")
