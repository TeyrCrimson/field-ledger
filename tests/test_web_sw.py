"""The board opens at once with no hub, even when the hub hangs rather than refuses (Wi-Fi off,
mobile data on: Teyr's S25+ waited a long time for a blank page). Runs the real sw.js in node
against a stand-in hub and cache. Needs `node`."""

import json
import shutil
import subprocess

import pytest

from field_ledger import hub

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")

HARNESS = """
import { readFileSync } from "node:fs";
import vm from "node:vm";
const mode = process.argv[1];                 // hangs | answers | same (what was saved)
const answers = mode !== "hangs";
const posted = [];
const alive = setInterval(() => {}, 1_000);   // node doesn't wait for AbortSignal.timeout alone
const saved = new Map([["https://hub/board.js", "saved board"], ["https://hub/state.json", "saved kit"]]);
const on = {};
const cache = { put: async (req, res) => saved.set(req.url, await res.text()), addAll: async () => {} };
vm.runInNewContext(readFileSync("sw.js", "utf8"), {
  self: { addEventListener: (type, fn) => (on[type] = fn),
          clients: { matchAll: async () => [{ postMessage: (m) => posted.push(m) }] } },
  caches: { open: async () => cache,
            match: async (req) => saved.has(req.url) ? new Response(saved.get(req.url)) : undefined },
  fetch: (req, { signal } = {}) => answers ? Promise.resolve(new Response(
      mode === "same" ? saved.get(req.url) : "live " + req.url.slice(12)))
    : new Promise((_, reject) => signal?.addEventListener("abort", () => reject(signal.reason))),
  Response, Headers, URL, AbortSignal,
});
async function open(path) {
  const start = Date.now();
  let answer;
  const later = [];
  on.fetch({ request: new Request("https://hub/" + path), respondWith: (p) => (answer = p),
             waitUntil: (p) => later.push(p) });
  const response = await answer;
  const text = await response.text();
  const ms = Date.now() - start;
  await Promise.all(later);
  return { ms, text, flagged: response.headers.has("X-Saved-Copy") };
}
const board = await open("board.js");
const kit = await open("state.json");
console.log(JSON.stringify({ board, kit, next: saved.get("https://hub/board.js"), posted }));
clearInterval(alive);
"""


def run(hub_does):
    out = subprocess.run(["node", "--input-type=module", "-e", HARNESS, hub_does], cwd=hub.WEB_DIR,
                         capture_output=True, text=True, check=True, timeout=10)
    return json.loads(out.stdout)


def test_a_hanging_hub_still_opens_the_board_at_once_and_its_kit_within_the_limit():
    seen = run("hangs")
    assert seen["board"]["text"] == "saved board" and seen["board"]["ms"] < 200
    assert seen["kit"] == {"ms": seen["kit"]["ms"], "text": "saved kit", "flagged": True}
    assert 1_400 <= seen["kit"]["ms"] < 3_000          # api.js gives up at 3 s; this must beat it


def test_a_hub_that_answers_wins_for_the_kit_and_refreshes_the_files_for_next_time():
    seen = run("answers")
    assert seen["kit"]["text"] == "live state.json" and not seen["kit"]["flagged"]
    assert seen["board"]["text"] == "saved board"      # opened at once from the saved copy
    assert seen["next"] == "live board.js"             # and the next open has the hub's


def test_a_changed_board_file_tells_the_page_once_per_file_and_the_kit_never_does():
    """The kit changes on every refresh; only a board file means a newer board."""
    assert run("answers")["posted"] == ["updated"]     # board.js changed; state.json did too
    assert run("same")["posted"] == []
    assert run("hangs")["posted"] == []
