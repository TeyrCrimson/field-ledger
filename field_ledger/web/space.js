// The space (prototype, field 4b-2; F5 builds on it): locations laid out freely as icons,
// vehicles parked beside them, and a box of what's in each. It reads the same /state.json
// and writes through the same api.js as the board, so every move here is a real move, with
// the same rules, readback, Undo and offline queue.
//
// Tap a location or vehicle: the space slides it to the left edge and its box opens. In a
// box, items that look the same stack (same kind, colour and name) unless one needs a look.
// Tap an item for its menu; tap a stack to spread it; tap a case to open its box. Drag an
// item onto a case, a place or vehicle, or the box; hold it over ◀ ▶ to flip places while
// carrying it. Drag a location to rearrange the space (shared: layout.json in the ledger
// repo, never an event), or a vehicle onto another location to drive it there.
//
// ponytail: act / pickName / refresh repeat board.js's; when the space becomes the board
// (F5), board.js goes and these stay.
import { CAN_WAIT, Offline, flush, getState, me, post, send, setName, unsynced, waiting } from "./api.js";
import { addDialog, css as addCss } from "./components/add-form.js";
import { confirmDialog, css as confirmCss } from "./components/confirm.js";
import { button, describeWrite, dialogCss, el } from "./components/dom.js";
import { peoplePicker, css as peopleCss } from "./components/people.js";
import { LEVELS, box, css as spaceCss, menu, spot, tile } from "./components/space.js";
import { show, toast, css as toastCss } from "./components/toast.js";
import { unsyncedBadge, css as unsyncedCss } from "./components/unsynced.js";
import { icon, kindOf } from "./icons.js";

const REFRESH_MS = 10_000;
const TOAST_MS = 15_000;
const FLIP_MS = 600;                                    // hold an item over ◀ ▶ this long to flip
const HOLD_MS = 300;                                    // a finger holds this long to pick something up
const EDGE = 40;                                        // carrying within this of an edge scrolls
const EDGE_SPEED = 8;                                   // pixels a frame
const ZOOMS = ["Out", "Normal", "In"];                  // icons at 1×, 2×, 3×
const BOX_ZOOM = 2;                                     // a box stays at Normal whatever the space's zoom (Teyr)
const COLOURS = ["green", "blue", "red", "gold", "metal"];

const style = document.createElement("style");
style.textContent = [dialogCss, addCss, confirmCss, peopleCss, toastCss, unsyncedCss, spaceCss].join("\n");
document.head.append(style);

let latest = { places: [], nodes: [], people: [], needs_look: [] };
let layout = { positions: {}, colours: {} };
let zoom = Number(remembered("field-ledger-zoom")) || 2;
let open = null;                                        // what the box shows: a place or a node id
let spread = new Set();                                 // stacks tapped open
let busy = false;                                       // a drag is on: refreshes wait

const $ = (id) => document.getElementById(id);
const byId = () => new Map(latest.nodes.map((node) => [node.id, node]));

function remembered(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch { /* private mode: per visit */ }
  return null;
}

function showDialog(dialog) {
  dialog.addEventListener("close", () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
}

const say = (text, options = {}) => show($("toasts"), toast(text, options), TOAST_MS);

// --- what's where, and how it's doing ------------------------------------------------

const isPlace = (target) => latest.places.includes(target);
const kids = (target) => latest.nodes.filter((node) => node.parent === target);
const vehiclesAt = (place) => kids(place).filter((node) => node.vehicle);
const colourOf = (id) => layout.colours[id] ?? null;

function startOfToday() {
  const day = new Date();
  day.setHours(0, 0, 0, 0);
  return day;
}

// When this node went into the vehicle it's in: the latest move among it and whatever it's
// packed in below the vehicle (a battery packed into a case already in the van entered the
// van then). ponytail: `last` is the node's last event of any kind, not only moves; close
// enough until AUD and states arrive (F4).
function inVehicleSince(node, nodes) {
  const at = node.chain.findIndex((id) => nodes.get(id)?.vehicle);
  if (at < 0) return null;
  const times = [node, ...node.chain.slice(0, at).map((id) => nodes.get(id))]
    .map((n) => n?.last?.at).filter(Boolean).map((t) => new Date(t));
  return times.length ? { since: new Date(Math.max(...times)), vehicle: node.chain[at] } : null;
}

// ok / look / critical, and why, for one node, not counting what's inside it.
function ownStatus(node, nodes, pending) {
  let level = 0;
  const why = [];
  const raise = (to, text) => { level = Math.max(level, to); why.push(text); };
  if (node.conflict) raise(2, `⚠ two devices disagree: ${node.location} or ${node.conflict.other}`);
  if (node.label === "CRIT") raise(2, "security label CRIT");
  const ride = !node.vehicle && inVehicleSince(node, nodes);
  if (ride && ride.since < startOfToday()) {
    raise(2, `still in ${ride.vehicle} since ${ride.since.toLocaleDateString()}: unload it today`);
  }
  if (pending.has(node.id)) raise(1, `waiting for the hub: ${pending.get(node.id)}`);
  if (latest.needs_look.some((entry) => (entry.body.item ?? entry.body.build) === node.id)) {
    raise(1, "on Needs a look (the board at /)");
  }
  return { level, why };
}

// The worst of a place, vehicle or case and everything inside it.
function statusOf(target, nodes, pending) {
  const node = nodes.get(target);
  const status = node ? ownStatus(node, nodes, pending) : { level: 0, why: [] };
  for (const kid of kids(target)) {
    const inner = statusOf(kid.id, nodes, pending);
    status.level = Math.max(status.level, inner.level);
    status.why.push(...inner.why.map((line) => `${kid.id}: ${line}`));
  }
  return status;
}

// --- the space -------------------------------------------------------------------------

// Where a place sits, in Normal-zoom pixels. One without a saved spot goes in the next free
// cell of a two-wide grid.
function positionOf(place, index) {
  return layout.positions[place] ?? [24 + (index % 2) * 170, 24 + Math.floor(index / 2) * 150];
}

const scale = () => zoom / 2;

function placeImage(place) {
  return icon("place", colourOf(place));
}

function nodeImage(node) {
  return icon(kindOf(node), colourOf(node.id), node.vehicle ? "VAN" : null);
}

function renderField(nodes, pending) {
  const field = $("field");
  field.dataset.zoom = zoom;
  field.style.setProperty("--z", zoom);
  let width = 0, height = 0;
  const spots = latest.places.map((place, index) => {
    const [x, y] = positionOf(place, index);
    width = Math.max(width, x * scale() + 240);
    height = Math.max(height, y * scale() + 200);
    const vehicles = vehiclesAt(place).map((v) => ({
      id: v.id, image: nodeImage(v), level: LEVELS[statusOf(v.id, nodes, pending).level] }));
    const node = spot(place, placeImage(place), LEVELS[statusOf(place, nodes, pending).level], vehicles);
    node.style.left = `${x * scale()}px`;
    node.style.top = `${y * scale()}px`;
    node.querySelector(".here").classList.toggle("open", place === placeOf(open, nodes));
    return node;
  });
  // Room to slide any place to the left edge, however far right it sits.
  field.style.width = `${width + innerWidth}px`;
  field.style.height = `${height}px`;
  field.replaceChildren(...spots);
}

// The place a box target is at: itself, or where its vehicle or case is.
function placeOf(target, nodes) {
  if (!target) return null;
  return isPlace(target) ? target : nodes.get(target)?.location ?? null;
}

// Places and their vehicles, in the order they sit on the space: what ◀ ▶ flips through.
function flipOrder() {
  const placed = latest.places.map((place, index) => [place, positionOf(place, index)]);
  placed.sort(([, a], [, b]) => a[1] - b[1] || a[0] - b[0]);
  return placed.flatMap(([place]) => [place, ...vehiclesAt(place).map((v) => v.id)]);
}

// --- the box ---------------------------------------------------------------------------

function stacks(target, nodes, pending) {
  const groups = new Map();
  for (const node of kids(target)) {
    const status = ownStatus(node, nodes, pending);
    const inner = statusOf(node.id, nodes, pending);
    const key = node.container || status.level || node.group === "build"
      ? node.id                                          // never stacked: it's not like the others
      : `${kindOf(node)}|${colourOf(node.id) ?? ""}|${node.group}`;
    const group = groups.get(key) ?? { key, nodes: [], level: 0 };
    group.nodes.push(node);
    group.level = Math.max(group.level, inner.level);
    groups.set(key, group);
  }
  // What needs a look comes first, so nobody has to hunt for it.
  return [...groups.values()].sort((a, b) => b.level - a.level || a.key.localeCompare(b.key));
}

function tileFor(node, count, level, key) {
  const item = tile({ image: nodeImage(node), id: node.id, count, kind: kindOf(node),
                      group: node.group, level: LEVELS[level], container: node.container });
  item.dataset.id = node.id;
  item.dataset.stack = count > 1 ? key : "";
  return item;
}

function renderBox(nodes, pending) {
  if (!open || (!isPlace(open) && !nodes.has(open))) {
    open = null;
    $("box").hidden = true;
    return;
  }
  const target = nodes.get(open);
  const path = isPlace(open) ? [open] : [...target.chain.slice().reverse(), open];
  const frame = box({
    title: open,
    onFlip: flip,
    onTitle: () => targetMenu(open),
    onBack: target && !target.vehicle && !isPlace(open) ? () => openBox(target.parent) : null,
    onClose: () => openBox(null),
  });
  frame.id = "box";
  frame.dataset.zoom = BOX_ZOOM;
  frame.style.setProperty("--z", BOX_ZOOM);
  const body = frame.querySelector(".box-body");
  if (path.length > 1) body.append(el("p", "path", `in ${path.slice(0, -1).reverse().join(", in ")}`));
  const status = statusOf(open, nodes, pending);
  if (status.why.length) {
    const why = el("ul", "why");
    for (const line of status.why.slice(0, 6)) why.append(el("li", "", line));
    body.append(why);
  }
  const grid = el("div", "grid");
  grid.dataset.drop = open;
  for (const group of stacks(open, nodes, pending)) {
    const shown = group.nodes.length > 1 && spread.has(group.key) ? group.nodes : [group.nodes[0]];
    for (const node of shown) {
      const count = shown.length === 1 ? group.nodes.length : 1;
      grid.append(tileFor(node, count, count > 1 ? group.level : statusOf(node.id, nodes, pending).level, group.key));
    }
  }
  if (!grid.children.length) grid.append(el("p", "empty", "Nothing here. Drag something in."));
  body.append(grid);
  $("box").replaceWith(frame);
}

function openBox(target) {
  open = target;
  spread = new Set();
  render(true);                                         // even mid-drag: a flip while carrying
  // Slide the space so what the box belongs to sits at the left edge, beside the box: the
  // vehicle itself, or the place (a case shows the vehicle or place it's in).
  const node = byId().get(target);
  const shown = target && [target, ...(node?.chain ?? [])]
    .map((id) => $("field").querySelector(`[data-target="${CSS.escape(id)}"]`)).find(Boolean);
  if (!shown) return;
  const at = shown.getBoundingClientRect(), field = $("field").getBoundingClientRect();
  $("space").scrollTo({ left: at.left - field.left - 8, top: Math.max(0, at.top - field.top - 40),
                        behavior: "smooth" });
}

function flip(step) {
  const order = flipOrder();
  const nodes = byId();
  const at = order.indexOf(open) >= 0 ? order.indexOf(open) : order.indexOf(placeOf(open, nodes));
  openBox(order[(at + step + order.length) % order.length]);
}

// --- menus ---------------------------------------------------------------------------

function destinations(node) {
  const nodes = byId();
  const inside = (id) => nodes.get(id)?.chain.includes(node.id);
  const holders = latest.nodes.filter((n) => n.container && n.id !== node.id && !inside(n.id)
                                            && !(node.vehicle && !n.fixed));
  return [...latest.places, ...holders.map((n) => n.id)].filter((to) => to !== node.parent);
}

function colourMenu(id) {
  showDialog(menu(`Colour for ${id}`, [
    ...COLOURS.map((name) => [name[0].toUpperCase() + name.slice(1), () => setColour(id, name)]),
    ["Its own colour", () => setColour(id, null)],
  ]));
}

function details(id) {
  const nodes = byId();
  const node = nodes.get(id);
  const status = statusOf(id, nodes, pendingMap());
  const lines = node
    ? [`${node.group}`, `in ${node.chain.join(" in ") || "—"}`,
       node.last ? `last: ${node.last.by}, ${new Date(node.last.at).toLocaleString()}` : "no events yet"]
    : [`${kids(id).length} here, ${vehiclesAt(id).length} of them vehicles`];
  showDialog(menu(id, [], [...lines, ...(status.why.length ? status.why : ["all good"])]));
}

function itemMenu(id) {
  const node = byId().get(id);
  const choices = [
    ["Move to…", () => showDialog(menu(`Move ${id} to`, destinations(node).map((to) =>
      [to, () => act("move", { item: id, to })])))],
    ["Colour…", () => colourMenu(id)],
    ["Details", () => details(id)],
  ];
  if (node.container) choices.unshift(["Open", () => openBox(id)]);
  showDialog(menu(`${id} · ${node.group}`, choices));
}

function targetMenu(target) {
  if (!isPlace(target)) return itemMenu(target);
  showDialog(menu(target, [["Colour…", () => colourMenu(target)], ["Details", () => details(target)]]));
}

async function setColour(id, colour) {
  try {
    layout = (await post("layout", { colours: { [id]: colour } })).layout;
    render();
  } catch (error) {
    say(`Colour not saved: ${error.message}`, { error: true });
  }
}

async function savePosition(place, x, y) {
  try {
    layout = (await post("layout", { positions: { [place]: [x, y] } })).layout;
  } catch (error) {
    say(`Not saved: ${error.message} The layout needs the hub.`, { error: true });
  }
  render();
}

// --- dragging ----------------------------------------------------------------------------

// With a mouse, press and move a few pixels: a drag. With a finger, hold first (HOLD_MS),
// as when moving an app icon on a phone: a swipe that starts on an icon still scrolls the
// space or the box, and a tap still opens it. Anything that isn't a drag is a tap (the
// click handlers). While carrying, near the edge of the box or the space scrolls it.
function onPress(event) {
  const source = event.target.closest(".here, .vehicle, .tile");
  if (!source || event.button > 0) return;
  const x0 = event.clientX, y0 = event.clientY;
  const isLocation = source.classList.contains("here");
  const spotNode = source.closest(".spot");
  const start = isLocation ? [spotNode.offsetLeft, spotNode.offsetTop] : null;
  let ghost = null, over = null, flipTimer = null, edge = null, edgeLoop = 0, at = [x0, y0];
  let parked = false;
  let lifted = event.pointerType !== "touch";
  const holdTimer = lifted ? 0 : setTimeout(() => {
    lifted = true;
    source.classList.add("lifted");
    navigator.vibrate?.(10);
  }, HOLD_MS);
  // On the window, not the source: flipping the box mid-drag redraws it, source included.

  const hover = (x, y) => {
    const under = document.elementFromPoint(x, y);
    const target = under?.closest("[data-drop]");
    const flipper = under?.closest("[data-flip]");
    if (over !== target) {
      over?.classList.remove("drop-over");
      (over = target)?.classList.add("drop-over");
    }
    if (flipper && !flipTimer) {
      flipper.classList.add("armed");
      flipTimer = setTimeout(() => { flipTimer = null; park(); flip(Number(flipper.dataset.flip)); }, FLIP_MS);
    } else if (!flipper && flipTimer) {
      clearTimeout(flipTimer);
      flipTimer = null;
    }
    // Near an edge of whatever scrolls under the finger: scroll it, faster the closer.
    const pane = under?.closest(".box-body, .space");
    const box = pane?.getBoundingClientRect();
    const push = (low, high, v) => (v < low + EDGE ? -1 : v > high - EDGE ? 1 : 0) * EDGE_SPEED;
    edge = box && { pane, dx: pane.matches(".space") ? push(box.left, box.right, x) : 0,
                    dy: push(box.top, box.bottom, y) };
    if (edge && (edge.dx || edge.dy) && !edgeLoop) edgeLoop = requestAnimationFrame(nudge);
  };
  const nudge = () => {
    edgeLoop = 0;
    if (!ghost || !edge || (!edge.dx && !edge.dy)) return;
    edge.pane.scrollBy(edge.dx, edge.dy);
    hover(...at);
  };
  const move = (step) => {
    const far = Math.hypot(step.clientX - x0, step.clientY - y0) >= 8;
    if (!lifted) {                                     // moved before the hold: a swipe
      if (far) quit();
      return;
    }
    if (!busy && !far) return;
    busy = true;
    at = [step.clientX, step.clientY];
    if (isLocation) {                                  // the place itself slides with the finger
      spotNode.style.left = `${start[0] + step.clientX - x0}px`;
      spotNode.style.top = `${Math.max(0, start[1] + step.clientY - y0)}px`;
      return;
    }
    if (!ghost) {
      ghost = el("div", "ghost");
      ghost.style.setProperty("--icon", getComputedStyle(source).getPropertyValue("--icon"));
      ghost.append(source.querySelector(".icon").cloneNode(true));
      document.body.append(ghost);
    }
    ghost.style.transform = `translate(${step.clientX}px, ${step.clientY}px)`;
    hover(step.clientX, step.clientY);
  };
  // A finger's events go to the element it first touched, wherever it moves. A flip redraws
  // the space and the box, which would take that element off the page and the drag with it
  // (Teyr's S25+: carry, flip, drop failed; a mouse was fine). So it waits, hidden, on the page.
  const park = () => {
    if (parked) return;
    parked = true;
    source.style.display = "none";
    document.body.append(source);
  };
  // Once lifted, the finger carries the item: the page mustn't scroll under it.
  const hold = (touch) => { if (lifted) touch.preventDefault(); };
  const quit = () => {
    clearTimeout(holdTimer);
    clearTimeout(flipTimer);
    cancelAnimationFrame(edgeLoop);
    removeEventListener("pointermove", move);
    removeEventListener("pointerup", end);
    removeEventListener("pointercancel", end);
    removeEventListener("touchmove", hold);
    source.classList.remove("lifted");
    over?.classList.remove("drop-over");
    ghost?.remove();
    if (parked) source.remove();
    document.querySelectorAll(".flip.armed").forEach((b) => b.classList.remove("armed"));
  };
  const end = (up) => {
    quit();
    if (lifted && event.pointerType === "touch") source.dataset.dragged = "1";   // held: not a tap
    if (!busy) return;
    source.dataset.dragged = "1";                    // the click that follows isn't a tap
    busy = false;
    if (up.type === "pointercancel") return render();
    if (isLocation) {
      return savePosition(source.dataset.target, Math.round(spotNode.offsetLeft / scale()),
                          Math.round(spotNode.offsetTop / scale()));
    }
    const to = over?.dataset.drop;
    const item = source.dataset.id;
    if (to && to !== item && to !== byId().get(item)?.parent) act("move", { item, to });
    else render();
  };
  addEventListener("pointermove", move);
  addEventListener("pointerup", end);
  addEventListener("pointercancel", end);
  addEventListener("touchmove", hold, { passive: false });
}

function onTap(event) {
  const source = event.target.closest(".here, .vehicle, .tile");
  if (!source) return;
  if (source.dataset.dragged) return void delete source.dataset.dragged;
  if (!source.classList.contains("tile")) return openBox(source.dataset.target);
  const node = byId().get(source.dataset.id);
  if (source.dataset.stack) {
    spread.add(source.dataset.stack);
    return render();
  }
  if (node.container) return openBox(node.id);
  itemMenu(node.id);
}

// --- writing, as on the board ------------------------------------------------------------

const pendingMap = () => new Map(waiting().map(({ command, body }) =>
  [body.item ?? body.build, describeWrite(command, body)]));

async function act(command, body = {}) {
  const what = CAN_WAIT.has(command) ? describeWrite(command, body) : "";
  const sending = what ? say(`Sending: ${what}…`) : null;
  let answer;
  try {
    answer = await send(command, body);
  } catch (error) {
    return say(`Not logged: ${error.message}`, { error: true });
  } finally {
    sending?.dismiss();
  }
  if (answer.repeat || answer.queued) {
    say(answer.repeat ? `Already on its way: ${what}.`
                      : `Waiting for the hub: ${what}. It goes when the hub is back.`);
    return render();
  }
  if (answer.verdict === "CONFIRM") {
    return showDialog(confirmDialog(answer.messages,
                                    () => act(command, { ...answer.body, confirmed: true })));
  }
  if (answer.verdict === "REJECT" || answer.verdict === "IGNORE") {
    say(answer.messages.join(" ") || "Not logged.", { error: true });
  } else {
    say(answer.readback, { messages: answer.verdict === "WARN" ? answer.messages : [],
                           onUndo: CAN_WAIT.has(command) ? () => act("undo") : null });
  }
  await refresh();
}

function arrived(command, body, answer) {
  const what = describeWrite(command, body);
  if (answer.held) say(`Needs a look: ${what}. ${answer.messages.join(" ")}`, { error: true });
  else if (answer.event) say(`Sent: ${answer.readback || what}`);
  else say(`Not logged: ${what}. ${answer.messages.join(" ")}`, { error: true });
}

function pickName(required) {
  const dialog = peoplePicker(latest.people, {
    required,
    onPick: (name) => { setName(name); dialog.close(); renderHeader(); },
    onJoin: async (name) => {
      try {
        const answer = await post("people", { name });
        setName(answer.name);
        latest.people = answer.people;
        dialog.close();
        renderHeader();
        say(answer.readback);
      } catch (error) {
        say(`Couldn't add you: ${error.message}`, { error: true });
      }
    },
  });
  showDialog(dialog);
}

function setZoom(level) {
  zoom = level;
  remembered("field-ledger-zoom", String(zoom));
  render();
  renderHeader();
}

// The general menu, as a handheld RPG's start menu: one button in the bar, everything that
// isn't about one item behind it, so the space keeps the screen.
function generalMenu() {
  showDialog(menu("Menu", [
    [me.name ? `You: ${me.name}` : "Who are you?", () => pickName(false)],
    ["Add items", () => showDialog(addDialog(latest.places, (fields) => act("add", fields)))],
    ["Undo my last", () => act("undo")],
    ...ZOOMS.map((name, at) => [`Zoom: ${name}${at + 1 === zoom ? " ◀" : ""}`, () => setZoom(at + 1)]),
    ["The board (columns)", () => { location.href = "./"; }],
  ]));
}

function renderHeader() {
  $("actions").replaceChildren(...(unsynced() ? [unsyncedBadge(unsynced())] : []),
                               button("Menu", "primary", generalMenu));
  document.documentElement.style.setProperty("--bar-height", `${$("bar").offsetHeight}px`);
}

// Not while dragging (it would pull the space from under the finger), unless asked.
function render(always = false) {
  if (busy && !always) return;
  const nodes = byId();
  const pending = pendingMap();
  renderField(nodes, pending);
  renderBox(nodes, pending);
}

async function refresh() {
  try {
    latest = await getState();
    layout = await fetch("layout.json", { cache: "no-store" }).then((r) => r.json()).catch(() => layout);
    render();
    $("status").textContent = latest.saved
      ? `Can't reach the hub. Showing the space from ${new Date(latest.generated_at).toLocaleTimeString()}.`
      : `Updated ${new Date().toLocaleTimeString()}`;
    if (latest.saved) return renderHeader();
  } catch (error) {
    $("status").textContent = (error instanceof Offline ? error.message
                               : `Can't read the ledger (${error.message}).`) + " Showing the last space.";
    return renderHeader();
  }
  const sent = await flush(arrived);
  renderHeader();
  if (sent) await refresh();
}

const space = $("space");
space.addEventListener("pointerdown", onPress);
space.addEventListener("click", onTap);
// A held finger would open the phone's own long-press menu on an icon; the hold is ours.
document.addEventListener("contextmenu", (event) => {
  if (event.target.closest(".here, .vehicle, .tile")) event.preventDefault();
});
document.addEventListener("pointerdown", (event) => { if (event.target.closest("#box")) onPress(event); });
document.addEventListener("click", (event) => { if (event.target.closest("#box")) onTap(event); });
renderHeader();
await refresh();
if (!me.name || !latest.people.includes(me.name)) pickName(true);
setInterval(refresh, REFRESH_MS);
window.addEventListener("online", refresh);
window.addEventListener("resize", renderHeader);
document.fonts?.ready.then(renderHeader);           // the pixel font changes the bar's height
navigator.serviceWorker?.register("sw.js").catch(() => { /* works without it */ });
