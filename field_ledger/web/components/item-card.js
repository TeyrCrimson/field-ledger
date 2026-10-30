// One node on the board: its kind's icon (icons.js), its ID and group, what it's inside, a
// ⚠ when two devices disagree, its state if its kind has states, and for a build the
// deployed commit and security label.
import { icon, kindOf } from "../icons.js";
import { el } from "./dom.js";

export const css = `
.card {
  display: flex;
  align-items: center;
  gap: var(--space);
  min-height: var(--tap);
  margin: var(--px);
  padding: calc(var(--space) / 2) var(--space);
  background: var(--surface);
  box-shadow: var(--frame-thin);
  cursor: pointer;
}
.card .icon { flex: none; width: 32px; height: 32px; }
.card .icon.tile {
  display: grid;
  place-items: center;
  color: var(--on-accent);
  background: var(--trim);
  box-shadow: inset calc(-1 * var(--px)) calc(-1 * var(--px)) 0 rgb(0 0 0 / 0.25);
  font-family: var(--pixel);
  font-size: 0.75rem;
  font-weight: 700;
}
.card .body { flex: 1; min-width: 0; }
.card .id { font-family: var(--mono); font-weight: 600; }
.card .group { margin-left: 0.5em; color: var(--muted); font-size: 0.875rem; }
.card p { margin: 0.25em 0 0; font-size: 0.875rem; }
.card .inside, .card .build { color: var(--muted); }
.card .build { font-family: var(--mono); }
.card .state { float: right; color: var(--muted); font-family: var(--pixel); font-size: 0.8rem; }
/* The picked card: a ▶ points at it, as in a menu, and its row lights up. The pointer is
   5×9 pixels, stepped with a polygon so it needs no image and takes the text colour. */
.card { position: relative; }
.card.selected { background: var(--select); }
.card.selected::before {
  content: "";
  position: absolute;
  top: 50%;
  left: calc(-6 * var(--px) - 10px);
  width: 10px;
  height: 18px;
  margin-top: -9px;
  background: var(--text);
  clip-path: polygon(0 0, 20% 0, 20% 11.1%, 40% 11.1%, 40% 22.2%, 60% 22.2%, 60% 33.3%,
                     80% 33.3%, 80% 44.4%, 100% 44.4%, 100% 55.6%, 80% 55.6%, 80% 66.7%,
                     60% 66.7%, 60% 77.8%, 40% 77.8%, 40% 88.9%, 20% 88.9%, 20% 100%, 0 100%);
  animation: pointer 0.6s steps(1) infinite;
}
@keyframes pointer { 50% { transform: translateX(2px); } }
.card.conflict { background: var(--warn-bg); }
.card .warn { color: var(--warn); font-weight: 600; }
.card .sec { float: right; font-family: var(--pixel); font-size: 0.8rem; font-weight: 700; letter-spacing: 0.05em; }
.sec-crit { color: var(--sec-crit); }
.sec-high { color: var(--sec-high); }
.sec-med { color: var(--sec-med); }
.sec-low { color: var(--sec-low); }
.sec-na { color: var(--sec-na); }
.card.pending { outline: var(--px) dashed var(--accent); outline-offset: calc(2 * var(--px)); }
.card .pending-note { color: var(--accent); font-weight: 600; }
`;

export function itemCard(node) {
  const card = el("article", node.conflict ? "card conflict" : "card");
  const body = el("div", "body");
  card.append(icon(kindOf(node)), body);
  if (node.group === "build" && node.label) {
    body.append(el("span", `sec sec-${node.label.toLowerCase()}`, node.label));
  }
  if (node.state) body.append(el("span", "state", node.state));
  body.append(el("span", "id", node.id), el("span", "group", node.group));
  const inside = node.chain.slice(0, -1);              // chain: parent first, place last
  if (inside.length) body.append(el("p", "inside", `in ${inside.join(" in ")}`));
  if (node.group === "build") {
    body.append(el("p", "build", node.sha ? `deployed as ${node.sha.slice(0, 7)}` : "commit unknown"));
  }
  if (node.conflict) body.append(el("p", "warn", `⚠ or ${node.conflict.other}`));
  if (node.last) card.title = `Last: ${node.last.by}, ${new Date(node.last.at).toLocaleString()}`;
  return card;
}

// A write for this card that the hub hasn't logged yet: on its way, or waiting for the hub.
// Shown on the card itself, where the person is looking, not only in a toast.
export function markCard(card, text) {
  card.classList.add("pending");
  (card.querySelector(".body") ?? card).append(el("p", "pending-note", text));
}

export function unmarkCard(card) {
  card.classList.remove("pending");
  card.querySelector(".pending-note")?.remove();
}
