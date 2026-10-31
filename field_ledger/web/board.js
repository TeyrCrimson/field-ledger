// Puts the board together and wires it up. Components (components/*.js) only build elements
// and take callbacks, each with its own markup and style, so a design pass swaps those files
// (and tokens.css) without touching this one or the hub.
//
// Moving: tap a card to pick it, then tap a place, or a card that holds things (a case, a
// van: its kind says so) to pack it inside. Tapping any other card picks that one instead.
// On a laptop, drag it there. Every write goes through api.js to the hub, which answers with
// the same rules as `fl`: refused, asked (a confirm), or logged (a readback with Undo).
// With no hub a write waits on the phone ("N unsynced") and goes out when the hub is back:
// on reconnect, on each refresh, after each write. One the hub won't log as it arrives lands
// on Needs a look for a person to settle. Every write shows at once that it was taken,
// on its card and in a toast, so nobody taps it again to be sure.
import { CAN_WAIT, Offline, flush, getState, me, phoneSetup, post, send, setName, unsynced,
         waiting } from "./api.js";
import { actionBar, css as actionCss } from "./components/actionbar.js";
import { addDialog, css as addCss } from "./components/add-form.js";
import { addPhoneDialog, css as addPhoneCss } from "./components/add-phone.js";
import { auditDialog, css as auditCss } from "./components/audit.js";
import { column, css as columnCss } from "./components/column.js";
import { confirmDialog, css as confirmCss } from "./components/confirm.js";
import { button, describeWrite, dialogCss } from "./components/dom.js";
import { itemCard, markCard, unmarkCard, css as cardCss } from "./components/item-card.js";
import { icon } from "./icons.js";
import { needsLook, css as needsCss } from "./components/needs-look.js";
import { nudgeBanner, ownerDialog, css as ownerCss } from "./components/owner.js";
import { peoplePicker, css as peopleCss } from "./components/people.js";
import { show, toast, css as toastCss } from "./components/toast.js";
import { unsyncedBadge, css as unsyncedCss } from "./components/unsynced.js";

const REFRESH_MS = 10_000;
const TOAST_MS = 15_000;

const style = document.createElement("style");
style.textContent = [dialogCss, columnCss, cardCss, actionCss, addCss, confirmCss, peopleCss,
                     toastCss, needsCss, unsyncedCss, addPhoneCss, auditCss, ownerCss].join("\n");
document.head.append(style);

let latest = { places: [], nodes: [], people: [], needs_look: [] };
let selected = null;                                    // the picked node's id
let held = false;                                       // a refresh came while a card was picked

const $ = (id) => document.getElementById(id);
const nodeById = (id) => latest.nodes.find((node) => node.id === id);

function showDialog(dialog) {
  dialog.addEventListener("close", () => dialog.remove());
  document.body.append(dialog);
  dialog.showModal();
}

function say(text, options = {}) {
  return show($("toasts"), toast(text, options), TOAST_MS);
}

const cardOf = (id) => id && document.querySelector(`.card[data-id="${CSS.escape(id)}"]`);

// One write, end to end: no hub → it waits; refused → why; asked → confirm, then again
// with confirmed (same id and time); logged → the readback, with Undo.
async function act(command, body = {}) {
  const what = CAN_WAIT.has(command) ? describeWrite(command, body) : "";
  const card = what ? cardOf(body.item ?? body.build) : null;
  const sending = what ? say(`Sending: ${what}…`) : null;
  if (card) markCard(card, "Sending…");
  let answer;
  try {
    answer = await send(command, body);
  } catch (error) {
    return say(`Not logged: ${error.message}`, { error: true });
  } finally {
    sending?.dismiss();
    if (card) unmarkCard(card);
  }
  if (answer.repeat || answer.queued) {
    say(answer.repeat ? `Already on its way: ${what}.`
                      : `Waiting for the hub: ${what}. It goes when the hub is back.`);
    select(null);
    render();
    return renderHeader();
  }
  if (answer.verdict === "CONFIRM") {
    return showDialog(confirmDialog(answer.messages,
                                    () => act(command, { ...answer.body, confirmed: true })));
  }
  if (answer.verdict === "REJECT" || answer.verdict === "IGNORE") {
    say(answer.messages.join(" ") || "Not logged.", { error: true });
  } else {
    say(answer.readback, {
      messages: answer.verdict === "WARN" ? answer.messages : [],
      onUndo: CAN_WAIT.has(command) ? () => act("undo") : null,
    });
  }
  select(null);
  await refresh();
}

// What happened to a write that waited. Already logged (a resend) needs no word.
function arrived(command, body, answer) {
  const what = describeWrite(command, body);
  if (answer.held) {
    say(`Needs a look: ${what}. ${answer.messages.join(" ")}`, { error: true });
  } else if (answer.event) {
    say(`Sent: ${answer.readback || what}`);    // no readback: it had already landed
  } else {
    say(`Not logged: ${what}. ${answer.messages.join(" ")}`, { error: true });
  }
}

function moveTo(target) {
  if (selected && target !== selected) act("move", { item: selected, to: target });
}

// The banner's tap: pick the ⚠ card after the one picked now (the first, if none), and
// bring it into view just above the bar (centring it would put it under a tall bar).
function showNextConflict() {
  const open = latest.nodes.filter((node) => node.conflict);
  if (!open.length) return;
  const next = open[(open.findIndex((node) => node.id === selected) + 1) % open.length];
  select(next.id);
  const card = cardOf(next.id);
  const barTop = $("actionbar").firstElementChild?.getBoundingClientRect().top ?? innerHeight;
  if (card) scrollBy(0, card.getBoundingClientRect().bottom - barTop + 16);
}

function select(id) {
  selected = id;
  const node = id && nodeById(id);
  $("board").classList.toggle("picking", Boolean(node));
  for (const card of document.querySelectorAll(".card")) {
    card.classList.toggle("selected", card.dataset.id === id);
  }
  $("actionbar").replaceChildren(...(node ? [actionBar(node, latest.places, {
    onMove: moveTo,
    onResolve: (place) => act("resolve", { item: node.id, to: place }),
    onLabel: (label) => act("label", { build: node.id, label }),
    onState: (state) => act("state", { item: node.id, state }),
    onCancel: () => select(null),
  })] : []));
  const bar = $("actionbar").firstElementChild;            // toasts sit above the bar, never on it
  $("toasts").style.bottom = bar ? `${bar.offsetHeight + 8}px` : "";
  if (!id && held) render();
}

function cardFor(node, pending) {
  const card = itemCard(node);
  if (pending.has(node.id)) markCard(card, `Waiting for the hub: ${pending.get(node.id)}`);
  card.dataset.id = node.id;
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.draggable = true;
  card.addEventListener("dragstart", (event) => {
    event.dataTransfer.setData("text/plain", node.id);
    select(node.id);
  });
  return card;
}

// Never under a picked card: replacing the cards mid-drag can cancel the drop (seen once on
// a laptop, 2026-10-28). The newest state waits until the card is dropped or let go.
function render() {
  held = Boolean(selected);
  if (held) return;
  const pending = new Map(waiting().map(({ command, body }) =>
    [body.item ?? body.build, describeWrite(command, body)]));
  const byPlace = new Map(latest.places.map((place) => [place, []]));
  for (const node of latest.nodes) {
    if (node.location) byPlace.get(node.location).push(node);   // a place itself has none
  }
  const columns = [...byPlace].map(([place, nodes]) => {
    const section = column(place, nodes.map((node) => cardFor(node, pending)));
    section.dataset.place = place;
    return section;
  });
  $("board").replaceChildren(...columns);
  const banner = latest.owner && nudgeBanner(latest.owner, me.name, () => act("owner", { to: me.name }),
                                             showNextConflict);
  $("nudge").replaceChildren(...(banner ? [banner] : []));
  $("needs-look").replaceChildren(...(latest.needs_look.length ? [needsLook(latest.needs_look, {
    onLog: (entry) => act("settle", { id: entry.id, how: "log" }),
    onDismiss: (entry) => act("settle", { id: entry.id, how: "dismiss" }),
  })] : []));
  select(nodeById(selected) ? selected : null);
}

// One listener for the whole board: a card picks (or receives) the selection; the rest of a
// column is the place itself.
function onBoardTap(event) {
  const card = event.target.closest(".card");
  if (card) {
    if (!selected) return select(card.dataset.id);
    if (card.dataset.id === selected) return select(null);
    return nodeById(card.dataset.id)?.container ? moveTo(card.dataset.id) : select(card.dataset.id);
  }
  const place = event.target.closest(".column");
  if (place) moveTo(place.dataset.place);
}

function wireBoard() {
  const board = $("board");
  board.addEventListener("click", onBoardTap);
  board.addEventListener("keydown", (event) => {
    if ((event.key === "Enter" || event.key === " ") && event.target.closest(".card")) {
      event.preventDefault();
      onBoardTap(event);
    }
  });
  board.addEventListener("dragover", (event) => {
    if (event.target.closest(".column")) event.preventDefault();
  });
  board.addEventListener("drop", (event) => {
    event.preventDefault();
    const card = event.target.closest(".card");
    const into = card && nodeById(card.dataset.id)?.container;   // else: that card's place
    moveTo(into ? card.dataset.id : event.target.closest(".column")?.dataset.place);
  });
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

// A button with a pixel icon in front (not an emoji: every phone draws those its own way).
function withIcon(node, kind) {
  node.prepend(icon(kind));
  return node;
}

function renderHeader() {
  $("actions").replaceChildren(
    ...(unsynced() ? [unsyncedBadge(unsynced())] : []),
    button(me.name ? `You: ${me.name}` : "Who are you?", "", () => pickName(false)),
    button("+ Add items", "", () => showDialog(addDialog(latest.places, (fields) => act("add", fields)))),
    button(`Owner: ${latest.owner?.name || "nobody"}`, "", openOwner),
    button(`Audit (${latest.audit?.due.length ?? 0})`, "", openAudit),
    button("Undo my last", "", () => act("undo")),
    withIcon(button("Add a phone", "", addPhone), "phone"),
  );
}

// A board saved by an older hub has no audit block: nothing to check, rather than a crash.
function openAudit() {
  const audit = latest.audit ?? { due: [], mismatches: [] };
  showDialog(auditDialog(audit, latest.nodes, latest.places,
                         (item, found) => act("audit", { item, found })));
}

function openOwner() {
  const owner = latest.owner ?? { name: "", open: 0, claimable: false };
  const dialog = ownerDialog(owner, latest.people, me.name, (to) => { dialog.close(); act("owner", { to }); });
  showDialog(dialog);
}

async function addPhone() {
  const setup = await phoneSetup();
  if (setup) return showDialog(addPhoneDialog(setup));
  say("Phones join a hub started with `field-ledger serve --lan`.", { error: true });
}

// The hub answered, so anything waiting goes now; if some did, read the board again.
async function refresh() {
  try {
    latest = await getState();
    render();
    if (latest.saved) {
      $("status").textContent = "Can't reach the hub. Showing the board from "
                              + `${new Date(latest.generated_at).toLocaleTimeString()}.`;
      return renderHeader();
    }
    $("status").textContent = held ? "Changes are waiting: drop or cancel the picked card to see them."
                                   : `Updated ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    $("status").textContent = (error instanceof Offline ? error.message
                               : `Can't read the board (${error.message}).`) + " Showing the last board.";
    return renderHeader();
  }
  const sent = await flush(arrived);
  renderHeader();
  if (sent) await refresh();
}

wireBoard();
renderHeader();
await refresh();
if (!me.name || !latest.people.includes(me.name)) pickName(true);
setInterval(refresh, REFRESH_MS);
window.addEventListener("online", refresh);
// Opens the board with no hub (sw.js). Only on a secure page; elsewhere this is undefined.
navigator.serviceWorker?.register("sw.js").catch(() => { /* the board works without it */ });
