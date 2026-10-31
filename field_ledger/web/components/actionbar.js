// What you can do with the card you picked: tap a place or another card to move it there,
// type a place, settle a ⚠, set a build's security label, or set an item's state.
//
// Each job is its own section under its own heading, so a ⚠'s place buttons never read as
// states (Teyr, 2026-10-31). A ⚠ comes first, in the nudge banner's colours: it's why
// the card was picked, more often than not.
import { button, el } from "./dom.js";

export const css = `
.actionbar {
  position: fixed;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 5;
  display: grid;
  gap: var(--space);
  padding: var(--space);
  background: var(--surface);
  box-shadow: var(--frame);
}
.board.picking { padding-bottom: 20rem; }    /* the bar never covers the last cards */
.actionbar p { margin: 0; }
.actionbar .head { display: flex; align-items: center; justify-content: space-between; gap: var(--space); }
.actionbar .head p { font-family: var(--pixel); font-size: 1.1rem; font-weight: 600; }
.actionbar section { display: grid; gap: calc(var(--space) / 2); }
.actionbar section + section { padding-top: var(--space); border-top: var(--px) solid var(--muted); }
.actionbar h3 { margin: 0; font-family: var(--pixel); font-size: 0.875rem; color: var(--muted); text-transform: uppercase; }
.actionbar .hint { color: var(--muted); font-size: 0.875rem; }
.actionbar form, .actionbar .row { display: flex; flex-wrap: wrap; gap: calc(var(--space) / 2); }
.actionbar section.settle { --trim: var(--warn); padding: var(--space); border: 0; background: var(--warn-bg); box-shadow: var(--frame-thin); }
.actionbar section.settle h3 { color: var(--warn); }
.actionbar section.settle + section { border-top: 0; padding-top: 0; }
.actionbar input { flex: 1; min-width: 8rem; }     /* the rest of its look: dom.js */
`;

function section(title, className, ...children) {
  const part = el("section", className);
  part.append(el("h3", "", title), ...children);
  return part;
}

function choices(options, current, onPick) {
  const row = el("div", "row");
  for (const option of options) {
    row.append(button(option, option === current ? "primary" : "", () => onPick(option)));
  }
  return row;
}

export function actionBar(node, places, { onMove, onResolve, onLabel, onState, onCancel }) {
  const bar = el("div", "actionbar");
  const head = el("div", "head");
  head.append(el("p", "", `${node.id} · ${node.group}`), button("Cancel", "", onCancel));
  bar.append(head);
  if (node.conflict) {
    bar.append(section("⚠ Two devices disagree: where is it?", "settle",
                       choices([node.conflict.latest, node.conflict.other], "", onResolve)));
  }
  const form = el("form", "");
  const input = el("input", "");
  input.placeholder = "Where to?";
  input.setAttribute("list", "places");
  const known = el("datalist", "");
  known.id = "places";
  for (const place of places) known.append(Object.assign(el("option", ""), { value: place }));
  form.append(input, known, Object.assign(button("Move", "primary"), { type: "submit" }));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (input.value.trim()) onMove(input.value.trim());
  });
  bar.append(section("Move", "", el("p", "hint", "Tap a place, or a case to pack it in. Or type where it went:"), form));
  if (node.group === "build") {
    bar.append(section("Security label", "", choices(["CRIT", "HIGH", "MED", "LOW", "NA"], node.label, onLabel)));
  }
  if (node.states) {                      // only kinds that have states: `fl kind BAT states ...`
    bar.append(section("State", "", choices(node.states, node.state, onState)));
  }
  return bar;
}
