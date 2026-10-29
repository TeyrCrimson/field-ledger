"""The team CA: one CA for every hub laptop of a team, so a phone sets up once.

These need the `openssl` command (as the hub does); without it they're skipped.
"""

import shutil
import subprocess
from datetime import date

import pytest

from field_ledger import cli, tls

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs openssl")

MONTH = f"{date.today():%Y-%m}"


def laptop(monkeypatch, tmp_path, name, passphrases=()):
    """Run `hub-ca` as one laptop: its own data folder, and these answers to the prompts."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / name))
    answers = iter(passphrases)
    monkeypatch.setattr(cli, "getpass", lambda prompt: next(answers))
    return tls.ca_dir()


@pytest.fixture
def outside(tmp_path):
    """Somewhere to export to that isn't inside a Git repo (pytest's tmp dirs aren't)."""
    folder = tmp_path / "usb"
    folder.mkdir()
    return folder


def test_the_ca_is_named_for_the_team_not_the_laptop(tmp_path):
    tls.ensure_ca(tmp_path / "a", "casio")
    tls.ensure_ca(tmp_path / "b")
    assert tls.ca_name(tmp_path / "a") == f"field-ledger hub casio CA {MONTH}"
    assert tls.ca_name(tmp_path / "b") == f"field-ledger hub CA {MONTH}"
    assert tls.ca_expires(tmp_path / "a").year == date.today().year + 3


def test_export_then_import_gives_the_second_laptop_the_same_ca(monkeypatch, tmp_path, outside,
                                                                 capsys):
    seen = []
    real_run = subprocess.run
    monkeypatch.setattr(tls.subprocess, "run", lambda args, **kw: seen.append(args)
                        or real_run(args, **kw))
    a = laptop(monkeypatch, tmp_path, "a", ["s3cret pass", "s3cret pass"])
    assert cli.main(["hub-ca", "new", "casio"]) == 0
    assert cli.main(["hub-ca", "export", str(outside / "casio.p12")]) == 0
    assert (outside / "casio.p12").stat().st_mode & 0o077 == 0

    b = laptop(monkeypatch, tmp_path, "b", ["s3cret pass"])
    assert cli.main(["hub-ca", "import", str(outside / "casio.p12")]) == 0
    assert (b / "ca.crt").read_bytes() == (a / "ca.crt").read_bytes()
    assert (b / "ca.key").stat().st_mode & 0o077 == 0 and b.stat().st_mode & 0o077 == 0
    tls.issue(b, ["192.168.1.7"])                        # laptop B's hub cert, A's CA
    assert subprocess.run(["openssl", "verify", "-CAfile", str(a / "ca.crt"), str(b / "hub.crt")],
                          capture_output=True).returncode == 0
    assert not any("s3cret pass" in " ".join(map(str, args)) for args in seen)
    cli.main(["hub-ca"])
    assert f'"field-ledger hub casio CA {MONTH}", until ' in capsys.readouterr().out


def test_a_wrong_passphrase_installs_nothing(monkeypatch, tmp_path, outside):
    laptop(monkeypatch, tmp_path, "a", ["right", "right"])
    cli.main(["hub-ca", "new", "casio"])
    cli.main(["hub-ca", "export", str(outside / "casio.p12")])
    b = laptop(monkeypatch, tmp_path, "b", ["wrong"])
    assert cli.main(["hub-ca", "import", str(outside / "casio.p12")]) == 1
    assert not b.exists() and not b.with_name("hub-ca.import").exists()


def test_a_different_ca_is_only_replaced_when_asked_and_says_what_phones_must_do(
        monkeypatch, tmp_path, outside, capsys):
    laptop(monkeypatch, tmp_path, "a", ["pw", "pw"])
    cli.main(["hub-ca", "new", "casio"])
    cli.main(["hub-ca", "export", str(outside / "casio.p12")])
    b = laptop(monkeypatch, tmp_path, "b", ["pw", "pw"])
    tls.ensure_ca(b, "old")
    mine = (b / "ca.crt").read_bytes()
    assert cli.main(["hub-ca", "import", str(outside / "casio.p12")]) == 1
    assert (b / "ca.crt").read_bytes() == mine
    capsys.readouterr()
    assert cli.main(["hub-ca", "import", str(outside / "casio.p12"), "--replace"]) == 0
    assert tls.ca_name(b) == f"field-ledger hub casio CA {MONTH}"
    assert f'Phones set up for "field-ledger hub old CA {MONTH}" must remove it' in \
        capsys.readouterr().out


def test_a_ca_that_could_vouch_for_the_internet_is_refused(monkeypatch, tmp_path, outside):
    """The hub hands its CA to phones, so importing an unconstrained one would let it speak
    for any site."""
    run = lambda *args: subprocess.run(["openssl", *args], cwd=outside, check=True,
                                       capture_output=True, input="pw\n", text=True)
    run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "30", "-keyout", "ca.key",
        "-out", "ca.crt", "-subj", "/CN=field-ledger hub casio CA",
        "-addext", "basicConstraints=critical,CA:TRUE")
    run("pkcs12", "-export", "-inkey", "ca.key", "-in", "ca.crt", "-passout", "stdin",
        "-out", "wide.p12")
    b = laptop(monkeypatch, tmp_path, "b", ["pw"])
    assert cli.main(["hub-ca", "import", str(outside / "wide.p12")]) == 1
    assert not b.exists()


def test_export_refuses_a_git_repo_and_an_empty_or_mistyped_passphrase(monkeypatch, tmp_path,
                                                                        outside):
    laptop(monkeypatch, tmp_path, "a", ["", "a", "b", "pw", "pw"])
    cli.main(["hub-ca", "new", "casio"])
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    assert cli.main(["hub-ca", "export", str(repo / "casio.p12")]) == 1
    assert cli.main(["hub-ca", "export", str(outside / "casio.p12")]) == 1     # empty
    assert cli.main(["hub-ca", "export", str(outside / "casio.p12")]) == 1     # a, then b
    assert not (outside / "casio.p12").exists() and not (repo / "casio.p12").exists()


def test_new_keeps_an_existing_ca_and_checks_the_team_name(monkeypatch, tmp_path):
    a = laptop(monkeypatch, tmp_path, "a")
    assert cli.main(["hub-ca", "new", "casio"]) == 0
    mine = (a / "ca.crt").read_bytes()
    assert cli.main(["hub-ca", "new", "other"]) == 1
    assert cli.main(["hub-ca", "new", "x/CN=evil", "--replace"]) == 1
    assert (a / "ca.crt").read_bytes() == mine
