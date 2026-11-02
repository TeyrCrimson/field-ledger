"""Light or dark: the person's choice from the board's toggle, else the phone's own setting,
followed live (Teyr, 2026-11-02). Runs the real theme.js in node. Needs `node`."""

import json
import shutil
import subprocess

import pytest

from field_ledger import hub

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")

HARNESS = """
import { readFileSync } from "node:fs";
import vm from "node:vm";
const code = readFileSync("theme.js", "utf8");
function page(choice, systemDark, storageWorks = true) {
  const night = { matches: systemDark, on: null, addEventListener(_, fn) { this.on = fn; } };
  const root = { dataset: {} };
  vm.runInNewContext(code, {
    matchMedia: () => night,
    localStorage: { getItem: () => { if (!storageWorks) throw new Error("private"); return choice; } },
    document: { documentElement: root },
  });
  const first = root.dataset.theme;
  night.matches = !systemDark;                         // the phone switches while the page is open
  night.on();
  return [first, root.dataset.theme];
}
console.log(JSON.stringify({
  system_light: page(null, false), system_dark: page(null, true),
  chose_light: page("light", true), chose_dark: page("dark", false),
  private_mode: page(null, true, false), junk: page("purple", true),
}));
"""


def test_a_choice_wins_and_otherwise_the_phone_decides_live():
    out = subprocess.run(["node", "--input-type=module", "-e", HARNESS], cwd=hub.WEB_DIR,
                         capture_output=True, text=True, check=True, timeout=10)
    assert json.loads(out.stdout) == {
        "system_light": ["light", "dark"], "system_dark": ["dark", "light"],   # follows the phone
        "chose_light": ["light", "light"], "chose_dark": ["dark", "dark"],     # a choice sticks
        "private_mode": ["dark", "light"], "junk": ["dark", "light"]}
