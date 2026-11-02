"""The Menu as a panel from the left, on the board and the space alike (Teyr, 2026-11-02):
items in the order given, a skipped one left out, Close last; picking one closes the panel,
then runs it. Runs the real drawer.js in node against a stand-in DOM. Needs `node`."""

import json
import shutil
import subprocess

import pytest

from field_ledger import hub

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")

HARNESS = """
class El {
  constructor(tag) { this.tag = tag; this.kids = []; this.on = {}; this.dataset = {}; }
  setAttribute() {}
  append(...kids) { for (const k of kids) if (typeof k === "object") this.kids.push(k); }
  prepend(k) { this.kids.unshift(k); }
  addEventListener(type, fn) { (this.on[type] ??= []).push(fn); }
  close() { this.closed = true; log.push("closed"); }
  all(tag) { return this.kids.flatMap((k) => [...(k.tag === tag ? [k] : []), ...k.all(tag)]); }
}
const log = [];
const stored = {};
globalThis.document = { createElement: (tag) => new El(tag), documentElement: { dataset: { theme: "light" } } };
globalThis.localStorage = { setItem: (k, v) => { stored[k] = v; } };
const { drawer, modeSwitch, themeItem } = await import("./components/drawer.js");
const panel = drawer("Menu", [["Audit (3)", () => log.push("audit")], null,
                              ["Undo my last", () => log.push("undo")], themeItem(),
                              ["Add a phone", () => {}, new El("canvas")]]);
const buttons = panel.all("button");
buttons[0].on.click[0]();
const theme = buttons.find((b) => b.textContent === "Dark mode");
theme.on.click[0]();
const afterOne = [theme.textContent, document.documentElement.dataset.theme];
theme.on.click[0]();
const afterTwo = [theme.textContent, document.documentElement.dataset.theme];
const lit = (here) => modeSwitch(here).kids.map((span) => [span.textContent, span.className]);
console.log(JSON.stringify({ labels: buttons.map((b) => b.textContent), log, stored,
                             afterOne, afterTwo,
                             phoneIcon: buttons[3].kids[0]?.tag ?? null,
                             board: lit("board"), space: lit("space") }));
"""


def test_the_menu_panel():
    out = subprocess.run(["node", "--input-type=module", "-e", HARNESS], cwd=hub.WEB_DIR,
                         capture_output=True, text=True, check=True, timeout=10)
    assert json.loads(out.stdout) == {
        "labels": ["Audit (3)", "Undo my last", "Dark mode", "Add a phone", "Close"],  # null skipped
        "log": ["closed", "audit"],                     # closes, then runs; the theme stays open
        "stored": {"field-ledger-theme": "light"},
        "afterOne": ["Light mode", "dark"], "afterTwo": ["Dark mode", "light"],   # relabels in place
        "phoneIcon": "canvas",                                           # the icon is back
        "board": [["Board", "on"], ["Space", ""]], "space": [["Board", ""], ["Space", "on"]]}
