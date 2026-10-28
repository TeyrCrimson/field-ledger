// The hub asked a question (a CONFIRM verdict): show why, and log it only on "yes".
import { button, el } from "./dom.js";

export const css = `
.confirm ul { margin: 0; padding-left: 1.2em; }
.confirm li + li { margin-top: 0.25em; }
`;

export function confirmDialog(messages, onYes) {
  const dialog = el("dialog", "confirm");
  const list = el("ul", "");
  for (const message of messages) list.append(el("li", "", message));
  const row = el("div", "row");
  row.append(button("Yes, log it", "primary", () => { dialog.close(); onYes(); }),
             button("No", "", () => dialog.close()));
  dialog.append(el("h2", "", "Check this first"), list, row);
  return dialog;
}
