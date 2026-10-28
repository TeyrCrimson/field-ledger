// "N unsynced": writes this phone has made that haven't reached the hub yet. They go out on
// their own when it's back; a phone that dies first loses only these.
import { el } from "./dom.js";

export const css = `
.unsynced {
  display: inline-flex;
  align-items: center;
  min-height: var(--tap);
  padding: 0 var(--space);
  color: var(--warn);
  background: var(--warn-bg);
  border: 1px solid var(--warn);
  border-radius: var(--radius);
  font-weight: 600;
}
`;

export function unsyncedBadge(count) {
  const badge = el("span", "unsynced", `${count} unsynced`);
  badge.title = "Logged on this phone, waiting for the hub";
  return badge;
}
