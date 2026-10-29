// Needs a look: writes that waited on a phone and that the hub wouldn't log as they arrived,
// refused or a question nobody was there to answer. They stay until a person logs or
// dismisses each one; the hub still checks every rule when it's logged.
import { button, describeWrite, el } from "./dom.js";

export const css = `
.needs-look {
  --trim: var(--warn);
  margin: calc(var(--space) + 3 * var(--px)) calc(var(--space) + 3 * var(--px)) 0;
  padding: var(--space);
  background: var(--warn-bg);
  box-shadow: var(--frame);
}
.needs-look h2 { margin: 0 0 var(--space); font-size: 1.15rem; }
.needs-look ul { display: grid; gap: var(--space); margin: 0; padding: 0; list-style: none; }
.needs-look li { margin: var(--px); padding: calc(var(--space) / 2) var(--space); background: var(--surface); box-shadow: var(--frame-thin); }
.needs-look p { margin: 0.25em 0 0; font-size: 0.875rem; }
.needs-look .what { margin: 0; font-family: var(--mono); font-size: 1rem; font-weight: 600; }
.needs-look .who { color: var(--muted); }
.needs-look .row { display: flex; flex-wrap: wrap; gap: calc(var(--space) / 2); margin-top: calc(var(--space) / 2); }
`;

export function needsLook(entries, { onLog, onDismiss }) {
  const section = el("section", "needs-look");
  section.setAttribute("aria-label", "Needs a look");
  section.append(el("h2", "", `Needs a look (${entries.length})`));
  const list = el("ul", "");
  for (const entry of entries) {
    const item = el("li", "");
    const when = new Date(entry.body.occurred_at ?? entry.recorded_at).toLocaleString();
    const row = el("div", "row");
    // A question gets its yes; a refusal can only be tried again, under the same rules.
    row.append(button(entry.verdict === "CONFIRM" ? "Log it anyway" : "Try again", "primary",
                      () => onLog(entry)),
               button("Dismiss", "", () => onDismiss(entry)));
    item.append(el("p", "what", describeWrite(entry.command, entry.body)),
                el("p", "who", `${entry.body.actor || "?"} · ${when}`),
                ...entry.messages.map((message) => el("p", "", message)),
                row);
    list.append(item);
  }
  section.append(list);
  return section;
}
