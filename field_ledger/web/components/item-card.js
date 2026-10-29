// One node on the board: its ID and group, what it's inside, a ⚠ when two devices
// disagree, and for a build the deployed commit and security label.
import { el } from "./dom.js";

export const css = `
.card {
  min-height: var(--tap);
  padding: calc(var(--space) / 2) var(--space);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--bg);
}
.card .id { font-family: var(--mono); font-weight: 600; }
.card .group { margin-left: 0.5em; color: var(--muted); font-size: 0.875rem; }
.card p { margin: 0.25em 0 0; font-size: 0.875rem; }
.card .inside, .card .build { color: var(--muted); }
.card .build { font-family: var(--mono); }
.card { cursor: pointer; }
.card.selected { outline: 3px solid var(--accent); outline-offset: 2px; }
.card.conflict { border-color: var(--warn); background: var(--warn-bg); }
.card .warn { color: var(--warn); font-weight: 600; }
.card .sec { float: right; font-size: 0.75rem; font-weight: 700; letter-spacing: 0.05em; }
.sec-crit { color: var(--sec-crit); }
.sec-high { color: var(--sec-high); }
.sec-med { color: var(--sec-med); }
.sec-low { color: var(--sec-low); }
.sec-na { color: var(--sec-na); }
.card.pending { border: 2px dashed var(--accent); }
.card .pending-note { color: var(--accent); font-weight: 600; }
`;

export function itemCard(node) {
  const card = el("article", node.conflict ? "card conflict" : "card");
  if (node.group === "build" && node.label) {
    card.append(el("span", `sec sec-${node.label.toLowerCase()}`, node.label));
  }
  card.append(el("span", "id", node.id), el("span", "group", node.group));
  const inside = node.chain.slice(0, -1);              // chain: parent first, place last
  if (inside.length) card.append(el("p", "inside", `in ${inside.join(" in ")}`));
  if (node.group === "build") {
    card.append(el("p", "build", node.sha ? `deployed as ${node.sha.slice(0, 7)}` : "commit unknown"));
  }
  if (node.conflict) card.append(el("p", "warn", `⚠ or ${node.conflict.other}`));
  if (node.last) card.title = `Last: ${node.last.by}, ${new Date(node.last.at).toLocaleString()}`;
  return card;
}

// A write for this card that the hub hasn't logged yet: on its way, or waiting for the hub.
// Shown on the card itself, where the person is looking, not only in a toast.
export function markCard(card, text) {
  card.classList.add("pending");
  card.append(el("p", "pending-note", text));
}

export function unmarkCard(card) {
  card.classList.remove("pending");
  card.querySelector(".pending-note")?.remove();
}
