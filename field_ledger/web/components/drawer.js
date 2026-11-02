// The menu, as a panel from the left: one Menu button in the header, instead of a row of
// buttons that wrapped to four lines on a phone (Teyr, 2026-11-02). The board and the space
// both use it, most-used first. Picking an item closes the panel, then runs the item.
import { button, el } from "./dom.js";

export const css = `
dialog.drawer {
  inset: 0 auto 0 0;
  width: min(18rem, 85vw);
  height: 100%;
  max-height: 100%;
  margin: 0;
  border-radius: 0;
  overflow-y: auto;
}
dialog.drawer[open] { animation: drawer-in 0.12s steps(3); }   /* three pixel-art steps */
@keyframes drawer-in { from { transform: translateX(-100%); } }
@media (prefers-reduced-motion: reduce) { dialog.drawer[open] { animation: none; } }
dialog.drawer ul { display: grid; gap: var(--space); margin: 0; padding: 0; list-style: none; }
dialog.drawer li button { width: 100%; text-align: left; }
dialog.drawer li.close { margin-top: calc(var(--space) * 2); }
button.mode { display: inline-flex; gap: 0; padding: 0; overflow: hidden; }
button.mode span { display: flex; align-items: center; padding: 0 var(--space); color: var(--muted); }
button.mode span.on { color: var(--text); background: var(--select); }
`;

// `items` are [label, run, icon?, { stay }?]; a falsy one is skipped, so a caller can leave
// one out inline. An icon is a pixel one from icons.js (not an emoji: phones draw those their
// own way). A `stay` item keeps the panel open and takes the label its run() returns: the
// theme switches under your eyes, so you see it took (Teyr, 2026-11-02).
export function drawer(title, items) {
  const dialog = el("dialog", "drawer");
  const list = el("ul", "");
  for (const [label, run, picture, { stay = false } = {}] of items.filter(Boolean)) {
    const item = el("li", "");
    const choice = button(label, "", () => {
      if (stay) return void (choice.textContent = run());
      dialog.close();
      run();
    });
    if (picture) choice.prepend(picture);
    item.append(choice);
    list.append(item);
  }
  const close = el("li", "close");
  close.append(button("Close", "", () => dialog.close()));
  list.append(close);
  dialog.append(el("h2", "", title), list);
  dialog.addEventListener("click", (event) => {        // a tap on the dimmed page closes it
    const box = dialog.getBoundingClientRect();
    if (event.clientX > box.right || event.clientY > box.bottom) dialog.close();
  });
  return dialog;
}

// Board | Space: one switch on both pages, the page you're on lit; a tap goes to the other
// (Teyr, 2026-11-02: a hybrid toggle reads better than a menu item on each page).
export function modeSwitch(here) {
  const other = here === "board" ? "space.html" : "./";
  const node = button("", "mode", () => { location.href = other; });
  node.setAttribute("aria-label", here === "board" ? "Board, switch to the space" : "Space, switch to the board");
  for (const [name, page] of [["Board", "board"], ["Space", "space"]]) {
    node.append(el("span", page === here ? "on" : "", name));
  }
  return node;
}

// Dark mode / Light mode: the other one, kept on this phone (theme.js applies it before the
// next page draws). Once chosen, it no longer follows the phone's own setting.
export function themeItem(after = () => {}) {
  const label = () => (document.documentElement.dataset.theme === "dark" ? "Light mode" : "Dark mode");
  return [label(), () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    try { localStorage.setItem("field-ledger-theme", next); } catch { /* this visit */ }
    document.documentElement.dataset.theme = next;
    after();
    return label();
  }, null, { stay: true }];
}
