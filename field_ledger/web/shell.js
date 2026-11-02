// What the board and the space share around their own views, so the two pages work alike
// (Teyr, 2026-11-02): dialogs that keep the toasts in sight, the header (writes waiting, the
// Board | Space switch, the page's own buttons, Menu), the Menu, and the screens it opens.
// Each page hands in what it owns with useShell(): which page it is, its state, its act()
// and its name picker. The rest of each page is its own view.
import { me, phoneSetup, unsynced, waiting } from "./api.js";
import { addDialog, css as addCss } from "./components/add-form.js";
import { addPhoneDialog, css as addPhoneCss } from "./components/add-phone.js";
import { auditDialog, css as auditCss } from "./components/audit.js";
import { button } from "./components/dom.js";
import { drawer, modeSwitch, themeItem, css as drawerCss } from "./components/drawer.js";
import { ownerDialog, css as ownerCss } from "./components/owner.js";
import { relayDialog, css as relayCss } from "./components/relay.js";
import { show, toast, css as toastCss } from "./components/toast.js";
import { unsyncedBadge, css as unsyncedCss } from "./components/unsynced.js";
import { icon } from "./icons.js";

const TOAST_MS = 15_000;
export const css = [addCss, addPhoneCss, auditCss, drawerCss, ownerCss, relayCss, toastCss,
                    unsyncedCss].join("\n");

let page = { here: "board", latest: () => ({}), act: async () => {}, pickName: () => {} };
export const useShell = (it) => { page = it; };

// A modal dialog sits above the whole page, toasts included, so the toasts move into the
// topmost open one: the audit screen stays open across many checks, each with its readback.
// Held here, not looked up: while a closing dialog takes it out, its id finds nothing.
export const toasts = document.getElementById("toasts");
const toastsHome = () => [...document.querySelectorAll("dialog[open]")].at(-1) ?? document.body;

export function showDialog(dialog) {
  dialog.addEventListener("close", () => { dialog.remove(); toastsHome().append(toasts); });
  document.body.append(dialog);
  dialog.showModal();
  dialog.append(toasts);
}

export const say = (text, options = {}) => show(toasts, toast(text, options), TOAST_MS);

// The header: Menu first, on the side its panel opens from (Teyr, 2026-11-02), the switch,
// the page's own buttons (`own`), then what needs seeing now: writes waiting.
export function header(...own) {
  const latest = page.latest();
  return [
    button("Menu", "primary", openMenu),
    modeSwitch(page.here),
    ...own,
    ...(unsynced() ? [unsyncedBadge(unsynced())] : []),
    ...(unsynced() && latest.relay?.bot
      ? [button("Send through Telegram", "", () => showDialog(relayDialog(latest.relay.bot, waiting())))] : []),
  ];
}

// The same on both pages, most-used first. The order is a guess until there's field use.
function openMenu() {
  const latest = page.latest(), act = page.act;
  showDialog(drawer("Menu", [
    [`Audit (${latest.audit?.due.length ?? 0})`, openAudit],
    ["Undo my last", () => act("undo")],
    ["+ Add items", () => showDialog(addDialog(latest.places, (fields) => act("add", fields)))],
    [`Owner: ${latest.owner?.name || "nobody"}`, openOwner],
    [me.name ? `You: ${me.name}` : "Who are you?", () => page.pickName(false)],
    ["Add a phone", addPhone, icon("phone")],
    themeItem(),
  ]));
}

// A board saved by an older hub has no audit block: nothing to check, rather than a crash.
let auditOpen = null;                                   // the audit screen, while it's open
const drawAudit = () => {
  const latest = page.latest();
  return auditDialog(latest.audit ?? { due: [], mismatches: [] }, latest.nodes, latest.places,
                     (item, found) => page.act("audit", { item, found }));
};

export function openAudit() {
  auditOpen = drawAudit();
  auditOpen.addEventListener("close", () => { auditOpen = null; });
  showDialog(auditOpen);
}

// After each answered write, the open audit screen is redrawn from the hub's list: an undone
// or refused check comes back, and the count and mismatches stay true. Not on the timed
// refresh, which would wipe a place half-typed into Elsewhere…. A write that waits offline
// keeps its row away, as the check is taken. Each page's act() calls this.
export function redrawAudit() {
  if (!auditOpen) return;
  auditOpen.replaceChildren(...drawAudit().childNodes);
  toastsHome().append(toasts);                          // it was inside, unless a dialog is above
}

export function openOwner() {
  const latest = page.latest();
  const owner = latest.owner ?? { name: "", open: 0, claimable: false };
  const dialog = ownerDialog(owner, latest.people, me.name, (to) => { dialog.close(); page.act("owner", { to }); });
  showDialog(dialog);
}

async function addPhone() {
  const setup = await phoneSetup();
  if (setup) return showDialog(addPhoneDialog(setup));
  say("Phones join a hub started with `field-ledger serve --lan`.", { error: true });
}
