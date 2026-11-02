"""A toast closes by being tapped, so it has no × (Teyr, 2026-10-30); Undo is its only button,
and a keyboard closes it with Enter. Runs the real toast.js in node against a stand-in DOM.
Needs `node`."""

import json
import shutil
import subprocess

import pytest

from field_ledger import hub

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")

HARNESS = """
class El {
  constructor(tag) { this.tag = tag; this.kids = []; this.on = {}; this.cls = new Set(); this.parent = null; }
  set className(v) { this.cls = new Set(v.split(" ").filter(Boolean)); }
  get classList() { return { add: (c) => this.cls.add(c), contains: (c) => this.cls.has(c) }; }
  get childElementCount() { return this.kids.length; }
  get isConnected() { return this.parent !== null; }
  setAttribute() {}
  append(...kids) { for (const k of kids) if (typeof k === "object") { k.parent = this; this.kids.push(k); } }
  remove() { this.parent?.kids.splice(this.parent.kids.indexOf(this), 1); this.parent = null; }
  addEventListener(type, fn) { (this.on[type] ??= []).push(fn); }
  fire(type, extra = {}) {
    const event = { target: this, preventDefault() {}, ...extra };
    for (let n = this; n; n = n.parent) for (const fn of n.on[type] ?? []) fn(event);
  }
  click() { this.fire("click"); }
  closest(tag) { for (let n = this; n; n = n.parent) if (n.tag === tag) return n; return null; }
  all(tag) { return this.kids.flatMap((k) => [...(k.tag === tag ? [k] : []), ...k.all(tag)]); }
}
globalThis.document = { createElement: (tag) => new El(tag) };
globalThis.matchMedia = () => ({ matches: true });        // reduced motion: the text is there at once
const { show, toast } = await import("./components/toast.js");
const buttons = (node) => node.all("button").map((b) => b.textContent);
const box = new El("div");
const plain = show(box, toast("✓ BAT-12 · was in Case A → van"), 60_000);
const undo = toast("✓ BAT-13 → van", { onUndo: () => {} });
const typed = show(box, toast("✓ BAT-14 → van"), 60_000);
plain.fire("keydown", { key: "Enter" });
typed.fire("keydown", { key: "a" });
console.log(JSON.stringify({ plain: buttons(plain), undo: buttons(undo), focusable: plain.tabIndex,
                             enterCloses: !plain.isConnected, otherKeysDont: typed.isConnected }));
plain.dismiss();
typed.dismiss();
"""


def test_a_toast_has_no_close_button_and_enter_puts_it_away():
    out = subprocess.run(["node", "--input-type=module", "-e", HARNESS], cwd=hub.WEB_DIR,
                         capture_output=True, text=True, check=True, timeout=10)
    assert json.loads(out.stdout) == {"plain": [], "undo": ["Undo"], "focusable": 0,
                                      "enterCloses": True, "otherKeysDont": True}
