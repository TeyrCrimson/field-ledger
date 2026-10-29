"""The QR encoder that puts the hub's setup address on the laptop screen.

Checked once by outside tools (2026-10-29, never repo dependencies): zxing-cpp decoded all
153 codes of a sweep (every version 1-6, every mask, edges of each capacity), and segno
built identical modules wherever the data fills its version. The fingerprints below pin
those verified outputs.
"""

import hashlib

import pytest

from field_ledger import qr


def fingerprint(dark):
    return hashlib.sha256("".join("1" if m else "0" for row in dark for m in row)
                          .encode()).hexdigest()[:16]


def test_reed_solomon_matches_the_textbook_example():
    """HELLO WORLD at 1-M, the worked example most QR tutorials use."""
    data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
    assert qr.rs_remainder(data, qr.rs_divisor(10)) == [196, 35, 39, 119, 235, 215, 231, 226,
                                                        93, 23]


@pytest.mark.parametrize("text, size, digest", [
    ("x" * 14, 21, "759a539d1bf76152"),                         # identical to segno
    ("http://192.168.1.3:8765/setup", 29, "5196d33546d1595e"),  # decoded by zxing-cpp
])
def test_verified_codes_stay_the_same(text, size, digest):
    dark = qr.encode(text)
    assert len(dark) == size and fingerprint(dark) == digest


@pytest.mark.parametrize("length, version", [(1, 1), (14, 1), (15, 2), (26, 2), (27, 3),
                                             (42, 3), (43, 4), (106, 6)])
def test_the_smallest_version_that_fits(length, version):
    assert qr.version_for(length) == version


def test_too_long_is_refused():
    with pytest.raises(ValueError, match="106 at most"):
        qr.encode("q" * 107)


def test_finders_sit_in_three_corners():
    dark = qr.encode("http://192.168.1.3:8765/setup")
    n = len(dark)
    finder = [[max(abs(x - 3), abs(y - 3)) != 2 for x in range(7)] for y in range(7)]
    for top, left in ((0, 0), (0, n - 7), (n - 7, 0)):
        assert [row[left:left + 7] for row in dark[top:top + 7]] == finder


def test_both_format_copies_agree():
    """The format bits are written twice so a scratch on one copy still scans."""
    dark = qr.encode("http://192.168.1.3:8765/setup")
    n = len(dark)
    first = [dark[i][8] for i in (0, 1, 2, 3, 4, 5, 7, 8)] + [dark[8][x] for x in (7, 5, 4, 3, 2, 1, 0)]
    second = [dark[8][n - 1 - i] for i in range(8)] + [dark[n - 7 + i][8] for i in range(7)]
    assert first == second


def test_terminal_rendering_has_a_quiet_zone():
    lines = qr.terminal(qr.encode("a")).splitlines()
    assert len(lines) == (21 + 9) // 2 and all(line.startswith("\x1b[30;107m    ") for line in lines)
