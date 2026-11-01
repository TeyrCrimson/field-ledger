// The field-ops owner: who settles the ⚠s, and is nudged while any are open. The owner hands
// over to anyone on the People list; with no owner, anyone takes it; once a nudge has gone
// unanswered for a day (every day counts), anyone can take over. The hub decides, so these
// buttons only offer what it would accept, and a handover needs the hub.
import { button, el } from "./dom.js";

export const css = `
.nudge {
  --trim: var(--warn);
  margin: calc(var(--space) + 3 * var(--px)) calc(var(--space) + 3 * var(--px)) 0;
  padding: var(--space);
  background: var(--warn-bg);
  box-shadow: var(--frame);
}
.nudge { cursor: pointer; }
.nudge p { margin: 0 0 calc(var(--space) / 2); }
.nudge .hint { color: var(--warn); font-size: 0.875rem; }
.owner .row { display: flex; flex-wrap: wrap; gap: calc(var(--space) / 2); }
`;

// Tapping the banner (anywhere but its button) picks the next ⚠ card, saving a hunt for it
// (Teyr, 2026-10-31). It takes focus and Enter or Space for a keyboard, as a toast does.
export function nudgeBanner(owner, me, onTake, onShow) {
  if (!owner.open) return null;
  const banner = el("section", "nudge");
  banner.setAttribute("aria-label", "Owner nudge");
  const who = owner.name ? `${owner.name}, the field-ops owner, is nudged to settle them.`
                         : "Nobody owns this ledger yet, so nobody is nudged.";
  banner.append(el("p", "", `⚠ ${owner.open} to settle. ${who}`),
                el("p", "hint", owner.open > 1 ? "Tap to show the next one." : "Tap to show it."));
  banner.tabIndex = 0;
  banner.addEventListener("click", (event) => { if (!event.target.closest("button")) onShow(); });
  banner.addEventListener("keydown", (event) => {
    if (event.target === banner && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      onShow();
    }
  });
  if (owner.claimable) banner.append(el("p", "", "Unanswered for a day: anyone can take over."));
  if (me && me !== owner.name && (owner.claimable || !owner.name)) {
    banner.append(button(owner.name ? "Take over" : "Take it", "primary", onTake));
  }
  return banner;
}

export function ownerDialog(owner, people, me, onPick) {
  const dialog = el("dialog", "owner");
  dialog.append(el("h2", "", "Field-ops owner"),
                el("p", "", owner.name ? `${owner.name} has it.` : "Nobody has it yet."));
  const row = el("div", "row");
  if (me && me === owner.name) {
    dialog.append(el("p", "hint", "Hand it over to:"));
    for (const name of people.filter((p) => p !== me)) row.append(button(name, "", () => onPick(name)));
  } else if (me && (!owner.name || owner.claimable)) {
    if (owner.claimable) dialog.append(el("p", "hint", `${owner.name} left a ⚠ unanswered for a day.`));
    row.append(button(owner.name ? "Take over" : "Take it", "primary", () => onPick(me)));
  } else {
    dialog.append(el("p", "hint", `Only ${owner.name} can hand it over. Anyone can take over once a ⚠ has waited a day.`));
  }
  row.append(button("Close", "", () => dialog.close()));
  dialog.append(row);
  return dialog;
}
