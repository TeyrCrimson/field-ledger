// "Who are you?": pick your name from the ledger's People list, or add yourself once.
// The name is logged_by on every move this browser logs.
import { button, el } from "./dom.js";

export const css = `
.people .names { display: grid; gap: calc(var(--space) / 2); }
.people .hint { margin: 0; color: var(--muted); font-size: 0.875rem; }
`;

// `required`: the first visit can't be dismissed without a name.
export function peoplePicker(people, { onPick, onJoin, required }) {
  const dialog = el("dialog", "people");
  dialog.append(el("h2", "", "Who are you?"),
                el("p", "hint", "Your name goes on every move you log from this phone."));
  const names = el("div", "names");
  for (const name of people) names.append(button(name, "", () => onPick(name)));
  const form = el("form", "");
  const input = el("input", "");
  input.placeholder = "Your name";
  input.autocomplete = "name";
  const label = el("label", "", people.length ? "Not on the list? I'm new:" : "You're the first. Your name:");
  label.append(input);
  const row = el("div", "row");
  row.append(Object.assign(button("Add me", "primary"), { type: "submit" }));
  if (!required) row.append(button("Cancel", "", () => dialog.close()));
  form.append(label, row);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (input.value.trim()) onJoin(input.value.trim());
  });
  if (required) dialog.addEventListener("cancel", (event) => event.preventDefault());
  dialog.append(names, form);
  return dialog;
}
