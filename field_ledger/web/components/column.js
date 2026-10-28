// A place on the board: its name, how many things are there, and their cards.
// Markup and style live together, so swapping this file restyles columns and nothing else.
import { el } from "./dom.js";

export const css = `
.column {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: var(--space);
}
.column h2 {
  display: flex;
  justify-content: space-between;
  margin: 0 0 var(--space);
  font-size: 1rem;
}
.column .count { color: var(--muted); font-weight: normal; }
.column ul { display: grid; gap: calc(var(--space) / 2); margin: 0; padding: 0; list-style: none; }
.column .empty { margin: 0; color: var(--muted); font-size: 0.875rem; }
`;

export function column(place, cards) {
  const section = el("section", "column");
  section.setAttribute("aria-label", place);
  const heading = el("h2", "", place);
  heading.append(el("span", "count", String(cards.length)));
  section.append(heading);
  if (!cards.length) {
    section.append(el("p", "empty", "Nothing here"));
    return section;
  }
  const list = el("ul", "");
  for (const card of cards) {
    const item = el("li", "");
    item.append(card);
    list.append(item);
  }
  section.append(list);
  return section;
}
