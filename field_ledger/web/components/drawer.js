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
`;

// `items` are [label, run]; a falsy one is skipped, so a caller can leave one out inline.
export function drawer(title, items) {
  const dialog = el("dialog", "drawer");
  const list = el("ul", "");
  for (const [label, run] of items.filter(Boolean)) {
    const item = el("li", "");
    item.append(button(label, "", () => { dialog.close(); run(); }));
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

// Dark mode / Light mode: the other one, kept on this phone (theme.js applies it before the
// next page draws). Once chosen, it no longer follows the phone's own setting.
export function themeItem(after = () => {}) {
  const dark = document.documentElement.dataset.theme === "dark";
  return [dark ? "Light mode" : "Dark mode", () => {
    try { localStorage.setItem("field-ledger-theme", dark ? "light" : "dark"); } catch { /* this visit */ }
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    after();
  }];
}
