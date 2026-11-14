// Find an item from the Menu (Teyr, 2026-11-02): type an ID, part of a name, or a serial, and
// see where each match is, instead of opening places, vans and cases one by one. Places match
// too (Teyr, 2026-11-14). v0 only shows where; tapping a result to jump to it is phase 2.
import { button, el } from "./dom.js";

export const css = `
dialog.find input { width: 100%; box-sizing: border-box; }
dialog.find ul { display: grid; gap: calc(var(--space) / 2); margin: var(--space) 0; padding: 0; list-style: none; }
dialog.find li { display: grid; }
dialog.find .where { color: var(--muted); font-size: 0.875rem; }
`;

const LIMIT = 20;                                       // a phone screen's worth; type more to narrow

// "bat12", "BAT 12" and "bat-12" all mean BAT-12: compare IDs without case or separators.
const squash = (text) => String(text).toLowerCase().replace(/[^a-z0-9]/g, "");

// Where a node is, innermost first, as `fl where` says it: "CAS-01 in VAN-01 at hq".
export function whereText(node) {
  if (!node.chain?.length) return node.fixed ? "a place" : "nowhere yet";
  const [place, ...inside] = [...node.chain].reverse();
  return inside.length ? `${inside.reverse().join(" in ")} at ${place}` : place;
}

// Matches for `query`: nodes by ID, name or serial, plus places that are only a name (older
// ledgers). An exact ID first, then by ID. Pure, so it's tested without a page.
export function findNodes(nodes, places, query) {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  const key = squash(q);
  const hits = nodes
    .filter((n) => (key && squash(n.id).includes(key))
                   || String(n.group).toLowerCase().includes(q)
                   || String(n.serial ?? "").toLowerCase().includes(q))
    .map((n) => ({ id: n.id, name: n.group, serial: n.serial ?? "", where: whereText(n) }));
  const known = new Set(nodes.map((n) => n.id));
  const named = places
    .filter((p) => !known.has(p) && p.toLowerCase().includes(q))
    .map((p) => ({ id: p, name: "", serial: "", where: "a place" }));
  const exact = (h) => (squash(h.id) === key ? 0 : 1);
  return [...hits, ...named].sort((a, b) => exact(a) - exact(b) || a.id.localeCompare(b.id));
}

// One result: "BAT-12 · Blue 6S · sn X", then where it is underneath.
export function resultLine(hit) {
  const item = el("li", "");
  const title = [hit.id, hit.name, hit.serial && `sn ${hit.serial}`].filter(Boolean).join(" · ");
  item.append(el("span", "", title), el("span", "where", hit.where));
  return item;
}

export function findDialog(nodes, places) {
  const dialog = el("dialog", "find");
  const input = el("input", "");
  input.type = "search";
  input.placeholder = "ID, name or serial";
  input.setAttribute("aria-label", "Find an item");
  input.autofocus = true;                               // showModal() focuses it: type straight away
  const list = el("ul", "");
  const status = el("p", "where", "");
  const draw = () => {
    const hits = findNodes(nodes, places, input.value);
    list.replaceChildren(...hits.slice(0, LIMIT).map(resultLine));
    status.textContent = !input.value.trim() ? ""
      : !hits.length ? "Nothing matches."
      : hits.length > LIMIT ? `${hits.length} matches; showing ${LIMIT}. Type more to narrow.` : "";
  };
  input.addEventListener("input", draw);
  dialog.append(el("h2", "", "Find an item"), input, status, list,
                button("Close", "", () => dialog.close()));
  return dialog;
}
