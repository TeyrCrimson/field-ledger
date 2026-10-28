"""The hub: serves the board to this laptop, and with `--lan` to phones on the field network.

F1 is read-only and serves two things. `/state.json` is the replayed state. Everything else
is a static file from the web front end (`web/`, or `--web-dir` to try a design). The front
end is plain files split into components, so a design pass replaces files and never
touches Python, and Python never writes HTML. It binds to 127.0.0.1 unless told otherwise:
there are no logins (the threat model is honest mistakes), so the LAN is opt-in.
"""

import ipaddress
import json
import socket
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from .ledger import service, store
from .ledger.state import State, ancestors, deployed_sha, fold

WEB_DIR = Path(__file__).parent / "web"
TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript",
         ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
         ".webmanifest": "application/manifest+json"}


def snapshot(state: State, open_: dict[str, tuple[str, str]], now: datetime) -> dict:
    """The replayed state in the shape the board reads. This shape is the contract
    between the hub and any front end (README "The hub"); the front end is free to change."""
    nodes = []
    for node, group in sorted(state.items.items()):
        chain = ancestors(state, node)                     # parent first, place last
        entry = {"id": node, "group": group, "fixed": node in state.fixed,
                 "parent": chain[0] if chain else "", "location": chain[-1] if chain else "",
                 "chain": chain}
        if group == "build":
            entry |= {"sha": deployed_sha(state, node), "label": state.labels.get(node, "")}
        if node in open_:
            entry["conflict"] = {"latest": open_[node][0], "other": open_[node][1]}
        last = state.last_event.get(node)
        if last:
            entry["last"] = {"by": last.actor, "at": last.ts.isoformat(), "event": last.id}
        nodes.append(entry)
    places = ({n["location"] for n in nodes if n["location"]}
              | {n for n in state.fixed if n not in state.where})
    return {"generated_at": now.isoformat(), "places": sorted(places), "nodes": nodes}


def board_state(ledger_dir: Path) -> dict:
    """Read the event files directly, like `show` and the stale-work board: no cache, no
    device, nothing written."""
    state = fold(store.read_events(ledger_dir))
    return snapshot(state, service.open_conflicts(state), datetime.now(timezone.utc))


class Board(BaseHTTPRequestHandler):
    """GET only. Any other method gets the server's stock 'unsupported' answer."""

    def __init__(self, *args, ledger_dir: Path, web_dir: Path, **kwargs):
        self.ledger_dir, self.web_dir = ledger_dir, web_dir
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        path = unquote(self.path.split("?", 1)[0])
        if path == "/state.json":
            body = json.dumps(board_state(self.ledger_dir), indent=1).encode()
            return self.send(HTTPStatus.OK, TYPES[".json"], body)
        root = self.web_dir.resolve()
        file = (root / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
        if not file.is_relative_to(root) or not file.is_file():     # no ../ out of web/
            return self.send(HTTPStatus.NOT_FOUND, "text/plain", b"not found")
        self.send(HTTPStatus.OK, TYPES.get(file.suffix, "application/octet-stream"),
                  file.read_bytes())

    def send(self, status: HTTPStatus, kind: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{kind}; charset=utf-8" if kind.startswith("text")
                         else kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")    # a design swap shows on reload
        self.end_headers()
        self.wfile.write(body)


def make_server(ledger_dir: Path, web_dir: Path = WEB_DIR, host: str = "127.0.0.1",
                port: int = 8765) -> ThreadingHTTPServer:
    """Port 0 picks a free one (tests); `server_address` says which."""
    return ThreadingHTTPServer((host, port), partial(Board, ledger_dir=ledger_dir,
                                                     web_dir=web_dir))


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
