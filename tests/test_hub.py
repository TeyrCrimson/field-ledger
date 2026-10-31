"""Field stage 1: the hub serves the board read-only, as /state.json plus the web front end.

The front end is plain files split into components; swapping one file (a design to try,
via --web-dir) changes that file and nothing else, and the hub never writes to the ledger.
"""

import json
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from dataclasses import replace

import pytest

from field_ledger import hub
from field_ledger.cli import main
from field_ledger.ledger import service
from field_ledger.ledger.model import Move
from field_ledger.ledger.state import fold
from field_ledger.ledger.store import read_events
from ledger_helpers import Clock, make_ctx, seed


@pytest.fixture
def ledger(tmp_path):
    """BAT-01 in CAS-01 in the van, a deployed and labelled build, and one ⚠ on BAT-02."""
    clock = Clock()
    ctx = make_ctx(tmp_path / "l.db", "teyr", clock)
    seed(ctx)                                               # BAT-01..03 truck, CAM-01 site-b
    service.submit_move(ctx, Move("BAT-01", "van"))
    service.submit_deploy(ctx, "feat/x", "drone-3", sha="4b7e0d1" + "0" * 33)
    service.submit_label(ctx, "feat/x", "HIGH")
    service.submit_move(ctx, Move("BAT-02", "van"))
    clock.advance(minutes=1)
    service.submit_move(replace(ctx, actor="yoeng", device="yoeng-phone"), Move("BAT-02", "site-b"))
    return ctx.ledger_dir


def start(ledger_dir, web_dir=hub.WEB_DIR):
    server = hub.make_server(hub.Hub(ledger_dir, web_dir, ledger_dir.parent / "hub.db"),
                             "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def get(url):
    with urllib.request.urlopen(url) as response:
        return response.status, response.headers["Content-Type"], response.read()


def status_of(url, method="GET"):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method=method)) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def test_state_json_is_the_replay(ledger):
    server, base = start(ledger)
    try:
        status, kind, body = get(f"{base}/state.json")
    finally:
        server.shutdown()
    served = json.loads(body)
    state = fold(read_events(ledger))
    expected = hub.snapshot(state, service.open_conflicts(state), Clock()())
    assert status == 200 and kind == "application/json"
    timed = ("generated_at", "audit")          # the hub runs on real time; audit: test_audit.py
    assert {k: v for k, v in served.items() if k not in timed} == \
        {k: v for k, v in expected.items() if k not in timed}
    nodes = {n["id"]: n for n in served["nodes"]}
    assert nodes["feat/x"].items() >= {"location": "drone-3", "label": "HIGH",
                                       "sha": "4b7e0d1" + "0" * 33}.items()
    assert nodes["BAT-02"]["conflict"] == {"latest": "site-b", "other": "van"}
    assert "drone-3" in served["places"] and "hq" in served["places"]


def test_the_page_and_its_modules_are_served(ledger):
    server, base = start(ledger)
    try:
        status, kind, page = get(f"{base}/")
        assert status == 200 and kind.startswith("text/html")
        assert b'<script type="module" src="board.js">' in page
        for path in ("board.js", "components/column.js", "components/item-card.js"):
            status, kind, _ = get(f"{base}/{path}")
            assert status == 200 and kind.startswith("text/javascript"), path
        assert get(f"{base}/tokens.css")[1].startswith("text/css")
    finally:
        server.shutdown()


def test_the_boards_font_is_served_from_the_hub_with_its_licence(ledger):
    """No CDN: a phone with no internet still gets the font, and the OFL travels with it."""
    server, base = start(ledger)
    try:
        status, kind, font = get(f"{base}/fonts/PixelifySans.ttf")
        assert status == 200 and kind == "font/ttf" and font[:4] == b"\x00\x01\x00\x00"
        status, kind, licence = get(f"{base}/fonts/OFL.txt")
        assert status == 200 and kind.startswith("text/plain") and b"SIL Open Font License" in licence
    finally:
        server.shutdown()


def test_a_design_swaps_one_file_and_nothing_else(ledger, tmp_path):
    design = tmp_path / "design"
    shutil.copytree(hub.WEB_DIR, design)
    (design / "components" / "item-card.js").write_text("// a new card\n")
    server, base = start(ledger, design)
    try:
        assert get(f"{base}/components/item-card.js")[2] == b"// a new card\n"
        for path in ("board.js", "components/column.js", "tokens.css", "index.html"):
            assert get(f"{base}/{path}")[2] == (hub.WEB_DIR / path).read_bytes(), path
    finally:
        server.shutdown()


def test_nothing_outside_the_web_folder(ledger):
    server, base = start(ledger)
    try:
        for path in ("/../hub.py", "/%2e%2e/hub.py", "/components/../../hub.py", "/nope.js"):
            assert status_of(base + path) == 404, path
    finally:
        server.shutdown()


def test_the_hub_writes_nothing(ledger):
    def snapshot():
        files = sorted(p.name for p in (ledger / "events").iterdir())
        log = subprocess.run(["git", "-C", str(ledger), "log", "--format=%H"],
                             capture_output=True, text=True, check=True).stdout
        return files, log

    before = snapshot()
    server, base = start(ledger)
    try:
        get(f"{base}/state.json")
        get(f"{base}/")
        assert status_of(f"{base}/state.json", "POST") >= 400            # read-only
    finally:
        server.shutdown()
    assert snapshot() == before


def test_serve_needs_a_ledger(tmp_path, capsys):
    assert main(["serve", "--ledger-dir", str(tmp_path / "none")]) == 1
    assert "No ledger at" in capsys.readouterr().out


def test_wsl_nat_is_spotted_only_inside_wsl():
    assert hub.behind_wsl_nat("192.168.8.10") is False                 # a router address
