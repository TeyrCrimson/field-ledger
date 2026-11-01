// The end-of-day audit: everything nobody moved or checked today, by place, and what today's
// checks found wrong. Each item takes one tap: Here, Elsewhere… (type or pick the place), or
// Missing (it goes to Lost). A check is written as it's tapped, so a phone that dies halfway
// loses none of the checks already made; it waits offline like any other write.
import { button, el } from "./dom.js";

export const css = `
.audit h3 { margin: var(--space) 0 calc(var(--space) / 2); font-size: 1rem; }
.audit .check { margin: var(--px) var(--px) var(--space); padding: calc(var(--space) / 2) var(--space); background: var(--surface); box-shadow: var(--frame-thin); }
.audit .what { margin: 0 0 calc(var(--space) / 2); font-family: var(--mono); font-weight: 600; }
.audit .row, .audit form { display: flex; flex-wrap: wrap; gap: calc(var(--space) / 2); }
.audit form { margin-top: calc(var(--space) / 2); }
.audit form[hidden] { display: none; }        /* the flex above would show it before Elsewhere… */
.audit form input { flex: 1; min-width: 8rem; }
.audit .wrong { color: var(--warn); }
`;

function check(node, onCheck) {
  const box = el("div", "check");
  const done = (found) => { box.remove(); onCheck(node.id, found); };
  const inside = (node.chain ?? []).slice(0, -1);
  box.append(el("p", "what", `${node.id} · ${node.group}` + (inside.length ? ` · in ${inside.join(" in ")}` : "")));
  const form = el("form", "");
  form.hidden = true;
  const input = el("input", "");
  input.placeholder = "Where was it?";
  input.setAttribute("list", "audit-places");
  form.append(input, Object.assign(button("Found here", "primary"), { type: "submit" }));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (input.value.trim()) done(input.value.trim());
  });
  const row = el("div", "row");
  row.append(button("✓ Here", "primary", () => done("")),
             button("Elsewhere…", "", () => { form.hidden = false; input.focus?.(); }),
             button("Missing", "", () => done("lost")));
  box.append(row, form);
  return box;
}

export function auditDialog(audit, nodes, places, onCheck) {
  const dialog = el("dialog", "audit");
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const byPlace = new Map();
  for (const id of audit.due) {
    const node = byId.get(id) ?? { id, group: "", location: "" };
    if (!byPlace.has(node.location)) byPlace.set(node.location, []);
    byPlace.get(node.location).push(node);
  }
  dialog.append(el("h2", "", "Audit"),
                el("p", "hint", `${audit.due.length} to check today · ${audit.mismatches.length} mismatches`));
  for (const [place, items] of byPlace) {
    dialog.append(el("h3", "", place || "nowhere"), ...items.map((node) => check(node, onCheck)));
  }
  if (!audit.due.length) dialog.append(el("p", "", "Nothing left to check today."));
  for (const wrong of audit.mismatches) {
    dialog.append(el("p", "wrong", `${wrong.item}: logged in ${wrong.logged || "—"}, `
                                   + `${wrong.found === "lost" ? "missing" : `found in ${wrong.found}`} (${wrong.by})`));
  }
  const known = el("datalist", "");
  known.id = "audit-places";
  for (const place of places) known.append(Object.assign(el("option", ""), { value: place }));
  const close = el("div", "row");
  // The dialog it sits in, not 'dialog': a redraw moves this row into the open one (board.js).
  close.append(button("Done", "", () => close.closest("dialog").close()));
  dialog.append(known, close);
  return dialog;
}
