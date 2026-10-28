// Who this browser is, and the one way the board writes: POST /api/<command>.
// Every write carries the person (picked from the People list) and this browser's device id,
// which is what lets the ⚠ rule tell two phones apart.
const KEY = "field-ledger";

function load() {
  try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch { return {}; }
}

function save() {
  try { localStorage.setItem(KEY, JSON.stringify(me)); } catch { /* private mode: per-visit */ }
}

// crypto.randomUUID() needs HTTPS and the hub is plain http on the router, so build one.
function newDevice() {
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  return "web-" + [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export const me = load();
if (!me.device) {
  me.device = newDevice();
  save();
}

export function setName(name) {
  me.name = name;
  save();
}

// The answer for any verdict, including a refusal. Throws only when the request itself
// failed (no hub, or a 400), with the hub's reason.
export async function post(command, body = {}) {
  const response = await fetch(`api/${command}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, actor: me.name ?? "", device: me.device }),
  });
  const answer = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(answer.error || `HTTP ${response.status}`);
  return answer;
}
