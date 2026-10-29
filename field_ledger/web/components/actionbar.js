// What you can do with the card you picked: tap a place or another card to move it there,
// type a place, settle a ⚠, or set a build's security label.
import { button, el } from "./dom.js";

export const css = `
.actionbar {
  position: fixed;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 5;
  display: grid;
  gap: calc(var(--space) / 2);
  padding: var(--space);
  background: var(--surface);
  box-shadow: var(--frame);
}
.board.picking { padding-bottom: 16rem; }    /* the bar never covers the last cards */
.actionbar p { margin: 0; }
.actionbar .hint { color: var(--muted); font-size: 0.875rem; }
.actionbar form, .actionbar .row { display: flex; flex-wrap: wrap; gap: calc(var(--space) / 2); }
.actionbar > p:first-child { font-family: var(--pixel); font-size: 1.1rem; font-weight: 600; }
.actionbar input { flex: 1; min-width: 8rem; }     /* the rest of its look: dom.js */
`;

export function actionBar(node, places, { onMove, onResolve, onLabel, onCancel }) {
  const bar = el("div", "actionbar");
  bar.append(el("p", "", `${node.id} · ${node.group}`),
             el("p", "hint", "Tap a place, or a case to pack it in. Or type where it went:"));
  const form = el("form", "");
  const input = el("input", "");
  input.placeholder = "Where to?";
  input.setAttribute("list", "places");
  const known = el("datalist", "");
  known.id = "places";
  for (const place of places) known.append(Object.assign(el("option", ""), { value: place }));
  form.append(input, known, Object.assign(button("Move", "primary"), { type: "submit" }),
              button("Cancel", "", onCancel));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (input.value.trim()) onMove(input.value.trim());
  });
  bar.append(form);
  if (node.conflict) {
    const row = el("div", "row");
    row.append(el("p", "hint", "Two devices disagree. It's in:"));
    for (const place of [node.conflict.latest, node.conflict.other]) {
      row.append(button(place, "", () => onResolve(place)));
    }
    bar.append(row);
  }
  if (node.group === "build") {
    const row = el("div", "row");
    row.append(el("p", "hint", "Security label:"));
    for (const label of ["CRIT", "HIGH", "MED", "LOW", "NA"]) {
      row.append(button(label, node.label === label ? "primary" : "", () => onLabel(label)));
    }
    bar.append(row);
  }
  return bar;
}
