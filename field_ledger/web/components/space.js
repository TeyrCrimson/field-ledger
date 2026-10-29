// The space's pieces: a spot (a location's icon, name and status, with its parked vehicles),
// a tile in a box (one item, or a stack of ones that look the same), the box itself, and a
// menu. They build elements only; space.js wires them up.
import { button, el } from "./dom.js";

export const LEVELS = ["ok", "look", "critical"];
const MARKS = { ok: ["✓", "All good"], look: ["?", "Needs a look"], critical: ["!", "Critical: settle it today"] };

export const css = `
.space {
  position: relative;
  height: calc(100dvh - var(--bar-height, 7rem));
  overflow: auto;
  overscroll-behavior: contain;
}
.field { position: relative; min-width: 100%; min-height: 100%; }
/* Zoom: --z is 1, 2 or 3, so a 16x16 sprite is drawn at a whole-number size. Label text
   steps with it, in rem, so the phone's own text size still applies. */
.field, .box { --icon: calc(16px * var(--z)); }
.field[data-zoom="1"], .box[data-zoom="1"] { --label: 0.75rem; }
.field[data-zoom="2"], .box[data-zoom="2"] { --label: 0.875rem; }
.field[data-zoom="3"], .box[data-zoom="3"] { --label: 1rem; }
.spot { position: absolute; display: flex; align-items: flex-start; gap: calc(var(--space) / 2); }
.spot .icon, .tile .icon, .ghost .icon { width: var(--icon); height: var(--icon); }
.here, .vehicle, .tile {
  display: grid;
  justify-items: center;
  gap: 0.2rem;
  min-width: var(--tap);
  min-height: var(--tap);
  max-width: 7rem;
  margin: 0;
  padding: 0.3rem;
  color: var(--text);
  background: transparent;
  box-shadow: none;
  font-family: var(--font);
  font-weight: 600;
  text-shadow: none;
  touch-action: manipulation;           /* a swipe scrolls; a drag starts after a hold */
  user-select: none;
  -webkit-user-select: none;
  -webkit-touch-callout: none;
}
.here.lifted, .vehicle.lifted, .tile.lifted { transform: translateY(calc(-1 * var(--px))); }
.lifted .name { outline: var(--px) solid var(--accent); outline-offset: var(--px); }
.here:active, .vehicle:active, .tile:active { transform: none; box-shadow: none; }
.name {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.1rem 0.35rem;
  font-size: var(--label);
  line-height: 1.2;
  text-align: center;
  overflow-wrap: anywhere;
  background: var(--surface);
  box-shadow: var(--frame-thin);
}
.tile .group { color: var(--muted); font-size: calc(var(--label) * 0.9); font-weight: 400; }
.parked { display: grid; gap: 0.2rem; }
.here.open .name { background: var(--select); }
.drop-over .name, .tile.drop-over { outline: var(--px) solid var(--accent); outline-offset: var(--px); }
.mark {
  display: inline-grid;
  place-items: center;
  min-width: 1.1em;
  height: 1.1em;
  padding: 0 0.15em;
  color: var(--on-accent);
  font-family: var(--pixel);
  font-size: 0.8em;
  font-weight: 700;
  line-height: 1;
}
.mark.ok { background: var(--ok); }
.mark.look { color: var(--text); background: var(--warn-bg); box-shadow: inset 0 0 0 2px var(--warn); }
.mark.critical { background: var(--error); }

/* The box: a window of what's in a place, vehicle or case. On a phone it covers all but a
   strip on the left, where the space keeps that place's own icon in view. */
.box {
  position: fixed;
  top: calc(var(--bar-height, 7rem) + 3 * var(--px));
  right: calc(3 * var(--px));
  bottom: calc(3 * var(--px));
  left: 7.5rem;
  z-index: 3;
  display: grid;
  grid-template-rows: auto 1fr;
  max-width: 34rem;
  margin-left: auto;
  background: var(--surface);
  box-shadow: var(--frame);
}
.box[hidden] { display: none; }
.box-bar {
  display: grid;
  grid-template-columns: auto 1fr auto auto;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem;
  background: var(--trim);
}
.box-bar button { min-width: var(--tap); padding: 0 0.5rem; }
.box-bar .title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.box-bar .flip.armed { background: var(--select); }
.box-body { overflow: auto; padding: var(--space); }
.box-body .path { margin: 0 0 0.5rem; font-weight: 600; }
.box-body .why { margin: 0 0 var(--space); color: var(--muted); font-size: 0.875rem; }
.box-body .why li { margin: 0.15rem 0; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(5.5rem, 1fr));
  gap: var(--space);
  min-height: 6rem;
  align-content: start;
}
.tile { max-width: none; }
.tile .count { font-family: var(--pixel); }
.grid .empty { grid-column: 1 / -1; margin: 0; color: var(--muted); }
.ghost {
  position: fixed;
  top: 0;
  left: 0;
  z-index: 20;
  pointer-events: none;
  translate: -50% -50%;
  opacity: 0.85;
}

/* A menu, as in a handheld RPG: a list of choices, ▶ at the one under your finger. */
dialog.menu { width: min(20rem, calc(100vw - 2 * var(--space) - 4 * var(--px))); }
.menu .choices { display: grid; gap: 0.25rem; margin: 0; padding: 0; list-style: none; }
.menu .choices button {
  position: relative;
  width: 100%;
  padding-left: 2rem;
  text-align: left;
  box-shadow: none;
  background: transparent;
}
.menu .choices button:hover, .menu .choices button:focus-visible { background: var(--select); outline: none; }
.menu .choices button:hover::before, .menu .choices button:focus-visible::before {
  content: "";
  position: absolute;
  top: 50%;
  left: 0.6rem;
  width: 10px;
  height: 18px;
  margin-top: -9px;
  background: var(--text);
  clip-path: polygon(0 0, 20% 0, 20% 11.1%, 40% 11.1%, 40% 22.2%, 60% 22.2%, 60% 33.3%,
                     80% 33.3%, 80% 44.4%, 100% 44.4%, 100% 55.6%, 80% 55.6%, 80% 66.7%,
                     60% 66.7%, 60% 77.8%, 40% 77.8%, 40% 88.9%, 20% 88.9%, 20% 100%, 0 100%);
}
.menu .lines { margin: 0; padding-left: 1.2em; }
.menu .lines li { margin: 0.2rem 0; }
`;

export function statusMark(level) {
  const [glyph, label] = MARKS[level];
  const mark = el("span", `mark ${level}`, glyph);
  mark.setAttribute("role", "img");
  mark.setAttribute("aria-label", label);
  mark.title = label;
  return mark;
}

function named(className, image, name, level) {
  const node = button("", className);
  const label = el("span", "name", name);
  label.append(statusMark(level));
  node.append(image, label);
  return node;
}

// A location on the space: its icon and name, and the vehicles parked there beside it.
export function spot(place, image, level, vehicles) {
  const node = el("div", "spot");
  node.dataset.place = place;
  const here = named("here", image, place, level);
  here.dataset.drop = place;
  here.dataset.target = place;
  const parked = el("div", "parked");
  for (const v of vehicles) {
    const vehicle = named("vehicle", v.image, v.id, v.level);
    vehicle.dataset.drop = v.id;
    vehicle.dataset.target = v.id;
    vehicle.dataset.id = v.id;
    parked.append(vehicle);
  }
  node.append(here, parked);
  return node;
}

// One item in a box, or a stack ("BAT ×4") of items that look the same.
export function tile({ image, id, count, kind, group, level, container }) {
  const node = button("", "tile");
  const label = el("span", "name", count > 1 ? `${kind} ` : id);
  if (count > 1) label.append(el("span", "count", `×${count}`));
  label.append(statusMark(level));
  node.append(image, label, el("small", "group", group));
  if (container) node.dataset.drop = id;
  return node;
}

// The box's frame: ◀ title ▶ ×, and a body the caller fills.
export function box({ title, onFlip, onTitle, onBack, onClose }) {
  const node = el("section", "box");
  node.setAttribute("aria-label", title);
  const bar = el("header", "box-bar");
  const back = button(onBack ? "‹" : "◀", "flip", onBack ?? (() => onFlip(-1)));
  back.setAttribute("aria-label", onBack ? "Back" : "Previous place");
  if (!onBack) back.dataset.flip = "-1";
  const next = button("▶", "flip", () => onFlip(1));
  next.dataset.flip = "1";
  next.setAttribute("aria-label", "Next place");
  const close = button("×", "", onClose);
  close.setAttribute("aria-label", "Close the box");
  bar.append(back, button(title, "title", onTitle), next, close);
  node.append(bar, el("div", "box-body"));
  return node;
}

// A menu: a title and choices; picking one closes it and runs it.
export function menu(title, choices, lines = []) {
  const dialog = el("dialog", "menu");
  dialog.append(el("h2", "", title));
  if (lines.length) {
    const list = el("ul", "lines");
    for (const line of lines) list.append(el("li", "", line));
    dialog.append(list);
  }
  const list = el("ul", "choices");
  for (const [label, run] of [...choices, ["Cancel", null]]) {
    const item = el("li", "");
    item.append(button(label, "", () => { dialog.close(); run?.(); }));
    list.append(item);
  }
  dialog.append(list);
  return dialog;
}
