"""The board offers a kind's states as buttons on a picked card, and only for kinds that have
them. Runs the real actionbar.js in node against a stand-in DOM. Needs `node`."""

import json
import shutil
import subprocess

import pytest

from field_ledger import hub

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")

HARNESS = """
class El {
  constructor(tag) { this.tag = tag; this.kids = []; this.on = {}; }
  setAttribute() {}
  append(...kids) { for (const k of kids) if (typeof k === "object") this.kids.push(k); }
  addEventListener(type, fn) { (this.on[type] ??= []).push(fn); }
  all(tag) { return this.kids.flatMap((k) => [...(k.tag === tag ? [k] : []), ...k.all(tag)]); }
}
globalThis.document = { createElement: (tag) => new El(tag) };
const { actionBar } = await import("./components/actionbar.js");
const sent = [];
const handlers = { onState: (s) => sent.push(s) };
const buttons = (node) => node.all("button").map((b) => [b.textContent, b.className]);
const battery = actionBar({ id: "BAT-01", group: "Battery", chain: ["truck"], state: "ready",
                            states: ["ready", "depleted"] }, [], handlers);
const camera = actionBar({ id: "CAM-01", group: "Camera", chain: ["truck"] }, [], handlers);
const torn = actionBar({ id: "BAT-02", group: "Battery", chain: ["van"], states: ["ready"],
                        conflict: { latest: "van", other: "store" } }, [], handlers);
const sections = (node) => node.all("section").map((s) => [s.className, s.all("h3")[0].textContent]);
battery.all("button").find((b) => b.textContent === "depleted").on.click[0]();
console.log(JSON.stringify({ battery: buttons(battery), camera: buttons(camera), sent,
                             torn: sections(torn) }));
"""


def test_a_picked_card_offers_its_kinds_states():
    out = subprocess.run(["node", "--input-type=module", "-e", HARNESS], cwd=hub.WEB_DIR,
                         capture_output=True, text=True, check=True, timeout=10)
    result = json.loads(out.stdout)
    assert result["battery"][-2:] == [["ready", "primary"], ["depleted", ""]]   # current one lit
    assert [b[0] for b in result["camera"]] == ["Cancel", "Move"]               # no states row
    assert result["sent"] == ["depleted"]


def test_each_job_has_its_own_section_and_a_conflict_comes_first():
    """A ⚠'s place buttons looked like states, all in one run (Teyr, 2026-10-31)."""
    out = subprocess.run(["node", "--input-type=module", "-e", HARNESS], cwd=hub.WEB_DIR,
                         capture_output=True, text=True, check=True, timeout=10)
    assert json.loads(out.stdout)["torn"] == [
        ["settle", "⚠ Two devices disagree: where is it?"], ["", "Move"], ["", "State"]]
