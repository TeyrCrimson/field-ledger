// Puts the board together: fetch /state.json, a column per place, a card per node.
// Each component in components/ carries its own markup and style, so a design pass swaps
// files there (and tokens.css) and never touches the hub. Read-only for now (F1).
import { column, css as columnCss } from "./components/column.js";
import { itemCard, css as cardCss } from "./components/item-card.js";

const REFRESH_MS = 10_000;

const style = document.createElement("style");
style.textContent = columnCss + cardCss;
document.head.append(style);

function render(state) {
  const byPlace = new Map(state.places.map((place) => [place, []]));
  for (const node of state.nodes) {
    if (node.location) byPlace.get(node.location).push(node);   // a place itself has none
  }
  const columns = [...byPlace].map(([place, nodes]) => column(place, nodes.map(itemCard)));
  document.getElementById("board").replaceChildren(...columns);
}

async function refresh() {
  const status = document.getElementById("status");
  try {
    const response = await fetch("state.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    render(await response.json());
    status.textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    status.textContent = `Can't reach the hub (${error.message}). Showing the last board.`;
  }
}

refresh();
setInterval(refresh, REFRESH_MS);
