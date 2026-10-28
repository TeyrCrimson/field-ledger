// Create items in the field without the CLI: N more of a group (BAT, CAS…), at a place.
import { button, el } from "./dom.js";

export const css = `
.add .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 var(--space); }
.add .check { display: flex; align-items: center; gap: 0.5em; min-height: var(--tap); }
.add .check input { width: 1.25rem; height: 1.25rem; min-height: 0; }
`;

function field(label, input) {
  const wrap = el("label", "", label);
  wrap.append(input);
  return wrap;
}

function input(attrs) {
  return Object.assign(el("input", ""), attrs);
}

export function addDialog(places, onAdd) {
  const dialog = el("dialog", "add");
  const form = el("form", "");
  const prefix = input({ required: true, maxLength: 3, pattern: "[A-Za-z]{3}", placeholder: "BAT" });
  const count = input({ required: true, type: "number", min: 1, max: 100, value: 1 });
  const name = input({ placeholder: "Blue 6S" });
  const at = input({ required: true, placeholder: "truck" });
  const holds = input({ type: "checkbox" });
  const holdsLabel = el("label", "check");
  holdsLabel.append(holds, " Can hold other things (a case, a van, a drone)");
  at.setAttribute("list", "add-places");
  const known = el("datalist", "");
  known.id = "add-places";
  for (const place of places) known.append(Object.assign(el("option", ""), { value: place }));
  const grid = el("div", "grid");
  grid.append(field("Kind (3 letters)", prefix), field("How many", count));
  const row = el("div", "row");
  row.append(Object.assign(button("Add", "primary"), { type: "submit" }),
             button("Cancel", "", () => dialog.close()));
  form.append(grid, field("Name", name), field("Where they are", at), known, holdsLabel, row);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    dialog.close();
    onAdd({ prefix: prefix.value.trim(), count: Number(count.value), name: name.value.trim(),
            at: at.value.trim(), container: holds.checked });
  });
  dialog.append(el("h2", "", "Add items"), form);
  return dialog;
}
