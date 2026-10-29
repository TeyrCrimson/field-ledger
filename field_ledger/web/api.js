// Who this browser is, and the one way the board writes: POST /api/<command>.
// Every write carries the person (picked from the People list) and this browser's device id,
// which is what lets the ⚠ rule tell two phones apart.
//
// Offline: every write gets its event id, time and sequence number here, when it's tapped.
// If the hub can't be reached, a move, add, label or resolve waits in this browser's queue
// and goes out, in order, when the hub is back; the id lets the hub log it once however often
// it's sent. Undo and joining need the hub.
//
// Feedback is instant: once a request has failed, the next write waits at once instead of
// trying again (the next refresh finds the hub), and tapping the same write again while it's
// still on its way or waiting adds nothing.
const KEY = "field-ledger";
const QUEUE = "field-ledger-queue";
const TIMEOUT_MS = 3_000;              // a hub that's there answers well inside this
export const CAN_WAIT = new Set(["move", "add", "label", "resolve"]);

function load(key, empty) {
  try { return JSON.parse(localStorage.getItem(key)) || empty; } catch { return empty; }
}

// ponytail: if storage is blocked the queue still holds while the tab stays open.
function keep(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode: per-visit */ }
}

function hex(n) {
  return [...crypto.getRandomValues(new Uint8Array(n))].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// crypto.randomUUID() needs HTTPS and the hub is plain http on the router, so build one (v4).
function newId() {
  const h = hex(16);
  const variant = ((parseInt(h[16], 16) & 0x3) | 0x8).toString(16);
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-4${h.slice(13, 16)}-${variant}${h.slice(17, 20)}-${h.slice(20)}`;
}

export const me = load(KEY, {});
// The phone numbers its own writes from 1. A device the hub numbered (before offline
// writes) gets a new id, so the two counts never mix.
if (!me.device || me.seq === undefined) {
  me.device = "web-" + hex(8);
  me.seq = 0;
  keep(KEY, me);
}

const queue = load(QUEUE, []);
const sending = new Set();
let away = false;                      // the last request couldn't reach the hub

export function setName(name) {
  me.name = name;
  keep(KEY, me);
}

export const unsynced = () => queue.length;
export const waiting = () => [...queue];

// Stamped when it's tapped, not when it reaches the hub. A resend (after a CONFIRM, or from
// the queue) keeps its stamp.
function stamp(body) {
  if (body.id) return body;
  me.seq += 1;
  keep(KEY, me);
  return { actor: me.name ?? "", device: me.device, ...body, id: newId(),
           occurred_at: new Date().toISOString(), seq: me.seq };
}

export class Offline extends Error {}

// The answer for any verdict, including a refusal. Throws Offline when the hub can't be
// reached, or Error when the request itself failed (a 400), with the hub's reason.
export async function post(command, body = {}) {
  let response;
  try {
    response = await fetch(`api/${command}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actor: me.name ?? "", device: me.device, ...body }),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    away = true;
    throw new Offline("Can't reach the hub.");
  }
  away = false;
  const answer = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(answer.error || `HTTP ${response.status}`);
  return answer;
}

// The board, read from the hub. A failure here also marks the hub away.
export async function getState() {
  let response;
  try {
    response = await fetch("state.json", { cache: "no-store", signal: AbortSignal.timeout(TIMEOUT_MS) });
  } catch {
    away = true;
    throw new Offline("Can't reach the hub.");
  }
  away = response.headers.has("X-Saved-Copy");          // the service worker's copy: no hub
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return { ...(await response.json()), saved: away };
}

// What "Add a phone" shows (the QR code and its address), or null: the hub isn't on the LAN.
export async function phoneSetup() {
  const response = await fetch("phone-setup.json", { cache: "no-store" }).catch(() => null);
  return response?.ok ? response.json() : null;
}

// A write without its stamp, so two taps of the same move compare equal.
function sameWrite(command, body) {
  const { id, occurred_at, seq, actor, device, confirmed, queued, ...write } = body;
  return command + JSON.stringify(write);
}

function wait(command, body) {
  queue.push({ command, body });
  keep(QUEUE, queue);
  return { queued: true, body };
}

// A write from the board. Answers like post(), or { queued: true, body } when it waits, or
// { repeat: true } when the same write is already on its way or waiting.
export async function send(command, body = {}) {
  if (command === "people" || command === "settle") return post(command, body);
  if (!CAN_WAIT.has(command)) {
    const stamped = stamp(body);
    return { ...(await post(command, stamped)), body: stamped };
  }
  const key = sameWrite(command, body);
  const last = queue.at(-1);
  if (sending.has(key) || (last && sameWrite(last.command, last.body) === key)) return { repeat: true };
  const stamped = stamp(body);
  if (away) return wait(command, stamped);
  sending.add(key);
  try {
    return { ...(await post(command, stamped)), body: stamped };
  } catch (error) {
    if (!(error instanceof Offline)) throw error;
    return wait(command, stamped);
  } finally {
    sending.delete(key);
  }
}

// Send what's waiting, oldest first, and stop at the first sign the hub is still away.
// onAnswer(command, body, answer) hears each one; resolves to how many went.
async function drain(onAnswer) {
  let sent = 0;
  while (queue.length) {
    const { command, body } = queue[0];
    let answer;
    try {
      answer = await post(command, { ...body, queued: true });
    } catch (error) {
      if (error instanceof Offline) break;
      answer = { verdict: "REJECT", messages: [error.message], event: null };  // a bad request
    }
    queue.shift();
    keep(QUEUE, queue);
    sent += 1;
    onAnswer(command, body, answer);
  }
  return sent;
}

let flushing = null;                // one drain at a time: refresh, reconnect and writes all call it
export function flush(onAnswer) {
  flushing ??= drain(onAnswer).finally(() => { flushing = null; });
  return flushing;
}
