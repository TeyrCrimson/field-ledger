"""Field stage 3b: HTTPS beside plain http, and what a phone needs to join by QR code.

These need the `openssl` command (as the hub does); without it they're skipped.
"""

import json
import shutil
import ssl
import subprocess
import threading
import urllib.error
import urllib.request

import pytest

from field_ledger import hub, qr, tls
from ledger_helpers import Clock, make_ctx, seed

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs openssl")


@pytest.fixture(scope="module")
def ca(tmp_path_factory):
    folder = tmp_path_factory.mktemp("hub-ca")
    tls.ensure_ca(folder)
    tls.issue(folder, ["127.0.0.1"])
    return folder


def serve(tmp_path, ca=None, setup_url=""):
    ctx = make_ctx(tmp_path / "l.db", "teyr", Clock())
    seed(ctx)
    the_hub = hub.Hub(ctx.ledger_dir, db=tmp_path / "hub.db", setup_url=setup_url,
                      ca_cert=ca and ca / "ca.crt", ca_name=ca and tls.ca_name(ca) or "")
    server = hub.make_server(the_hub, "127.0.0.1", 0, ca and tls.context(ca))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def get(url, cafile=None):
    context = ssl.create_default_context(cafile=str(cafile)) if cafile else None
    try:
        with urllib.request.urlopen(url, context=context, timeout=5) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def test_http_and_https_share_one_port(tmp_path, ca):
    server, port = serve(tmp_path, ca)
    try:
        plain = get(f"http://127.0.0.1:{port}/state.json")
        secure = get(f"https://127.0.0.1:{port}/state.json", cafile=ca / "ca.crt")
    finally:
        server.shutdown()
    assert plain[0] == secure[0] == 200
    assert json.loads(plain[2])["nodes"] == json.loads(secure[2])["nodes"]


def test_a_phone_that_doesnt_trust_the_hub_yet_is_refused_and_the_hub_carries_on(tmp_path, ca):
    server, port = serve(tmp_path, ca)
    try:
        with pytest.raises(urllib.error.URLError):
            get(f"https://127.0.0.1:{port}/")                     # the system CAs only
        assert get(f"http://127.0.0.1:{port}/")[0] == 200
    finally:
        server.shutdown()


def test_the_phone_setup_data_and_the_ca_download(tmp_path, ca):
    url = "http://192.168.1.3:8765/setup.html"
    server, port = serve(tmp_path, ca, setup_url=url)
    try:
        status, _, body = get(f"http://127.0.0.1:{port}/phone-setup.json")
        cert = get(f"http://127.0.0.1:{port}/ca.crt")
    finally:
        server.shutdown()
    setup = json.loads(body)
    assert status == 200 and setup["url"] == url and setup["ca_name"].startswith("field-ledger hub ")
    assert setup["qr"] == ["".join("1" if m else "0" for m in row) for row in qr.encode(url)]
    assert cert[0] == 200 and cert[1]["Content-Type"] == "application/x-x509-ca-cert"
    assert "field-ledger-hub.crt" in cert[1]["Content-Disposition"]
    assert cert[2] == (ca / "ca.crt").read_bytes()


def test_without_lan_or_https_there_is_nothing_to_set_up(tmp_path):
    server, port = serve(tmp_path)
    try:
        assert get(f"http://127.0.0.1:{port}/phone-setup.json")[0] == 404
        assert get(f"http://127.0.0.1:{port}/ca.crt")[0] == 404
    finally:
        server.shutdown()


def test_the_service_worker_learns_every_board_file(tmp_path):
    server, port = serve(tmp_path)
    try:
        files = json.loads(get(f"http://127.0.0.1:{port}/web-files.json")[2])
    finally:
        server.shutdown()
    assert {"index.html", "board.js", "sw.js", "setup.html", "components/item-card.js"} <= set(files)


def test_the_ca_is_made_once_and_its_key_stays_private(tmp_path):
    assert tls.ensure_ca(tmp_path) and not tls.ensure_ca(tmp_path)
    assert (tmp_path / "ca.key").stat().st_mode & 0o077 == 0
    assert tmp_path.stat().st_mode & 0o077 == 0


def test_the_ca_cannot_vouch_for_anything_on_the_internet(tmp_path, ca):
    """Installed on a phone, it can only speak for private addresses: a certificate it signs
    for a real site or a public address fails, so it can't be used to intercept."""
    for i, name in enumerate(["DNS:example.com", "IP:8.8.8.8"]):
        (tmp_path / f"x{i}.ext").write_text(f"subjectAltName={name}\n")
        run = lambda *args: subprocess.run(["openssl", *args], cwd=tmp_path, capture_output=True)
        run("req", "-newkey", "rsa:2048", "-nodes", "-keyout", f"x{i}.key", "-out", f"x{i}.csr",
            "-subj", "/CN=x")
        run("x509", "-req", "-in", f"x{i}.csr", "-CA", str(ca / "ca.crt"), "-CAkey",
            str(ca / "ca.key"), "-CAserial", f"x{i}.srl", "-CAcreateserial", "-days", "1",
            "-out", f"x{i}.crt", "-extfile", f"x{i}.ext")
        assert run("verify", "-CAfile", str(ca / "ca.crt"), f"x{i}.crt").returncode != 0
    assert run("verify", "-CAfile", str(ca / "ca.crt"), str(ca / "hub.crt")).returncode == 0
