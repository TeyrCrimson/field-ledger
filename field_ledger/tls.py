"""The hub's own certificate authority, so phones open the board over HTTPS: browsers only
run a service worker (the board opening with no hub) on a secure page.

The CA is made once per team (`hub-ca new`, or `serve` the first time) and can only vouch
for private network addresses and one reserved name: installed on a phone, it can't
impersonate anything on the internet. Its key stays in the hub laptops' data folder, never
in the ledger repo; `hub-ca export` / `import` carry it to another hub laptop. On every start the hub
signs itself a certificate for the address it has now, so the travel router and a phone
hotspot both work. Python can't make certificates, so this runs `openssl`.
"""

import os
import shutil
import ssl
import subprocess
from datetime import date
from pathlib import Path

# Name constraints: a type that isn't listed is unconstrained, so DNS is pinned to a
# reserved name that can't exist, and IP to the private ranges and this laptop.
CONSTRAINTS = ",".join(["permitted;DNS:field-ledger.invalid"] + [
    f"permitted;IP:{net}" for net in ("10.0.0.0/255.0.0.0", "172.16.0.0/255.240.0.0",
                                      "192.168.0.0/255.255.0.0", "127.0.0.0/255.0.0.0")])
CA_DAYS = 1095                  # a phone sets up once in three years
HUB_DAYS = 397                  # under the 398 days phones accept for a server certificate


def ca_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "field-ledger" / "hub-ca"


def available() -> bool:
    return shutil.which("openssl") is not None


def openssl(folder: Path, *args: str) -> None:
    subprocess.run(["openssl", *args], cwd=folder, check=True, capture_output=True)


def ca_name(folder: Path) -> str:
    """The name a phone lists it under: which laptop and when, so an old one is easy to
    spot and remove."""
    subject = subprocess.run(["openssl", "x509", "-in", "ca.crt", "-noout", "-subject",
                              "-nameopt", "multiline"], cwd=folder, check=True,
                             capture_output=True, text=True).stdout
    return subject.split("commonName", 1)[1].split("=", 1)[1].strip()


def ca_expires(folder: Path) -> date:
    end = subprocess.run(["openssl", "x509", "-in", "ca.crt", "-noout", "-enddate"], cwd=folder,
                         check=True, capture_output=True, text=True).stdout
    return date.fromtimestamp(ssl.cert_time_to_seconds(end.split("=", 1)[1].strip()))


def ensure_ca(folder: Path, team: str = "") -> bool:
    """Make the CA, once. False if it was already there. Named for the team, not the laptop:
    with export/import every hub laptop of a team shares it, so a phone sets up once."""
    if (folder / "ca.crt").exists():
        return False
    folder.mkdir(parents=True, exist_ok=True)
    folder.chmod(0o700)
    name = " ".join(filter(None, ["field-ledger hub", team, "CA", f"{date.today():%Y-%m}"]))
    openssl(folder, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", str(CA_DAYS),
            "-keyout", "ca.key", "-out", "ca.crt", "-subj", f"/CN={name}",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-addext", f"nameConstraints=critical,{CONSTRAINTS}")
    (folder / "ca.key").chmod(0o600)
    return True


def export(folder: Path, out: Path, passphrase: str) -> None:
    """ca.key and ca.crt as one passphrase-protected file, to set up another hub laptop. The
    passphrase reaches openssl on stdin: a command line is visible to every user."""
    subprocess.run(["openssl", "pkcs12", "-export", "-inkey", "ca.key", "-in", "ca.crt",
                    "-name", ca_name(folder), "-keypbe", "AES-256-CBC", "-certpbe", "AES-256-CBC",
                    "-macalg", "sha256", "-passout", "stdin", "-out", str(out.resolve())],
                   cwd=folder, input=passphrase + "\n", text=True, check=True, capture_output=True)
    out.chmod(0o600)


def unpack(file: Path, passphrase: str, into: Path) -> None:
    """An exported CA into the new folder `into`. ValueError for a wrong passphrase, or for a
    CA without exactly our name constraints: the hub hands its CA to phones, so an
    unconstrained one would let it speak for any site."""
    into.mkdir(mode=0o700, parents=True)
    # pkey / x509 strip pkcs12's "Bag Attributes" text: phones are served ca.crt as is.
    for part, tool, out in (("-nocerts", "pkey", "ca.key"), ("-nokeys", "x509", "ca.crt")):
        run = subprocess.run(["openssl", "pkcs12", "-in", str(file.resolve()), part, "-nodes",
                              "-passin", "stdin"], input=passphrase + "\n", text=True,
                             capture_output=True)
        if run.returncode:
            raise ValueError("wrong passphrase, or not an exported hub CA")
        subprocess.run(["openssl", tool, "-out", out], cwd=into, input=run.stdout, text=True,
                       check=True, capture_output=True)
    (into / "ca.key").chmod(0o600)
    shown = subprocess.run(["openssl", "x509", "-in", "ca.crt", "-noout", "-ext",
                            "nameConstraints"], cwd=into, capture_output=True, text=True).stdout
    wanted = ["X509v3 Name Constraints: critical", "Permitted:"] + [
        c.split(";", 1)[1] for c in CONSTRAINTS.split(",")]
    if [line.strip() for line in shown.splitlines()] != wanted:
        raise ValueError("not a field-ledger hub CA: it could vouch for addresses outside "
                         "private networks")


def issue(folder: Path, addresses: list[str]) -> None:
    """This hub's certificate for the addresses it has now, signed by the CA."""
    (folder / "hub.ext").write_text(
        "subjectAltName=" + ",".join(f"IP:{a}" for a in addresses)
        + "\nbasicConstraints=CA:FALSE\nextendedKeyUsage=serverAuth\n", encoding="utf-8")
    openssl(folder, "req", "-newkey", "rsa:2048", "-nodes", "-keyout", "hub.key",
            "-out", "hub.csr", "-subj", "/CN=field-ledger hub")
    openssl(folder, "x509", "-req", "-in", "hub.csr", "-CA", "ca.crt", "-CAkey", "ca.key",
            "-CAcreateserial", "-days", str(HUB_DAYS), "-out", "hub.crt", "-extfile", "hub.ext")
    (folder / "hub.key").chmod(0o600)


def context(folder: Path) -> ssl.SSLContext:
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(folder / "hub.crt", folder / "hub.key")
    return tls
