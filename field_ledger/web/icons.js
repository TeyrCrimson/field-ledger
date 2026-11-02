// Item icons: 16×16 pixel art, one per kind, drawn at exactly 2× so every pixel stays sharp.
// Drawn from scratch for this board, nothing copied from any game.
//
// How to draw one: a sprite is 16 rows of 16 letters, and its `key` says which colour each
// letter is. "." is see-through. The letters follow lesson 1: o outline, s shadow, b base,
// h highlight, in one colour ramp; others mark a second material. Light comes from the top
// left on every icon, so they look like one set.
//
// ponytail: icons live here, keyed by kind prefix. A team with its own kinds edits this
// file; per-ledger icons in settings.json come with F5.

// One palette for every icon: a few ramps, darkest (an outline) to lightest. The shadows
// lean towards blue and the highlights towards yellow, rather than just darker and lighter.
export const PALETTE = {
  ink: "#2b2d42",
  white: "#fbfbf4",
  green: ["#1f4a2a", "#3a7d44", "#5fb55a", "#a8e07a"],
  metal: ["#3d4250", "#6b7280", "#9aa0a8", "#d5d9de"],
  blue: ["#1e3557", "#335c99", "#4f8fd6", "#9cc8f5"],
  red: ["#5c1a1a", "#a8322a", "#e0604a", "#f5a08a"],
  gold: ["#6b4a0e", "#c98a1a", "#f2c84b", "#fff1a8"],
};

const ramp = (name) => ({ o: `${name}.0`, s: `${name}.1`, b: `${name}.2`, h: `${name}.3` });

export const SPRITES = {
  // A battery: the nub on the right is what makes it one. The bolt is two yellows.
  BAT: {
    key: { ...ramp("green"), m: "metal.0", t: "metal.2", l: "metal.3", y: "gold.2", Y: "gold.3" },
    rows: [
      "................",
      "................",
      "................",
      "..oooooooooo....",
      ".ohhhhhhhhhso...",
      ".ohbbbbbYybsommm",
      ".ohbbbbyybbsoltm",
      ".ohbbbYyyybsoltm",
      ".ohbbbbyybbsoltm",
      ".ohbbbyybbbsoltm",
      ".ohbbbybbbbsommm",
      ".ossssssssssso..",
      "..oooooooooo....",
      "................",
      "................",
      "................",
    ],
  },
  // A camera: grey body, a viewfinder bump, a glass lens with one white glint.
  CAM: {
    key: { o: "ink", s: "metal.0", b: "metal.1", h: "metal.2", r: "red.2",
           B: "blue.0", g: "blue.1", G: "blue.2", w: "white" },
    rows: [
      "................",
      "................",
      "...oooo.........",
      "...ohho.........",
      "..oohhoooooooo..",
      ".ohhhhhhhhhrrso.",
      ".ohbbbBBBBbbbso.",
      ".ohbbBwGGgBbbso.",
      ".ohbbBGGggBbbso.",
      ".ohbbBGgggBbbso.",
      ".ohbbBggggBbbso.",
      ".ohbbbBBBBbbbso.",
      ".osssssssssssso.",
      "..oooooooooooo..",
      "................",
      "................",
    ],
  },
  // A hard case: a handle, two latches, the seam where the lid closes.
  CAS: {
    key: { ...ramp("gold"), m: "metal.0", l: "metal.3" },
    rows: [
      "................",
      "................",
      ".....oooooo.....",
      ".....o....o.....",
      "..oooooooooooo..",
      ".ohhhhhhhhhhhso.",
      ".ohbbbbbbbbbbso.",
      ".ohblbbbbbblbso.",
      ".ohbmbbbbbbmbso.",
      ".osssssssssssso.",
      ".ohbbbbbbbbbbso.",
      ".ohbbbbbbbbbbso.",
      ".osssssssssssso.",
      "..oooooooooooo..",
      "................",
      "................",
    ],
  },
  // A phone, for "Add a phone": a glass screen with its glare in the top-left corner.
  phone: {
    key: { o: "ink", s: "metal.0", b: "metal.1", h: "metal.2", k: "metal.3", g: "blue.2", G: "blue.3" },
    rows: [
      "................",
      ".....oooooo.....",
      "....ohhhhhso....",
      "....ohGGggso....",
      "....ohGgggso....",
      "....ohggggso....",
      "....ohggggso....",
      "....ohggggso....",
      "....ohggggso....",
      "....ohggggso....",
      "....ohbbbbso....",
      "....ohbkkbso....",
      "....ohbbbbso....",
      "....osssssso....",
      ".....oooooo.....",
      "................",
    ],
  },
  // A location: a building with a red roof, a door and a window. Every place uses it.
  place: {
    key: { ...ramp("red"), w: "white", m: "metal.2", M: "metal.0", D: "blue.0", B: "blue.1",
           G: "blue.3" },
    rows: [
      "................",
      "................",
      "......oooo......",
      ".....ohhbbo.....",
      "....ohhbbbbo....",
      "...ohbbbbbbso...",
      "..ohbbbbbbbbso..",
      ".osssssssssssso.",
      "..MwwwwwwwwwwM..",
      "..MwwwwwwGGwmM..",
      "..MwDDDDwGGwmM..",
      "..MwDBBDwwwwmM..",
      "..MwDBBDwwwwmM..",
      "..MmDBBDmmmmmM..",
      "..MMMMMMMMMMMM..",
      "................",
    ],
  },
  // A van, facing right: the cab window is the only glass. Any vehicle kind without its own
  // sprite borrows it.
  VAN: {
    key: { ...ramp("blue"), g: "metal.3", k: "ink", m: "metal.2" },
    rows: [
      "................",
      "................",
      "................",
      "..oooooooo......",
      ".ohhhhhhhho.....",
      ".ohbbbbbbbsoo...",
      ".ohbbbbbbbsogo..",
      ".ohbbbbbbbsoggo.",
      ".ohbbbbbbbbbbbo.",
      ".ohbbbbbbbbbbso.",
      ".oskkksssskkkso.",
      "..okmkooookmko..",
      "...kkk....kkk...",
      "................",
      "................",
      "................",
    ],
  },
  // A build: a floppy disk, the old picture for "software". Metal shutter, a written label.
  build: {
    key: { ...ramp("blue"), m: "metal.1", t: "metal.2", l: "metal.3", w: "white" },
    rows: [
      "................",
      "..ooooooooooo...",
      ".ohhmmmmmmmbbo..",
      ".ohbmlltmtmbbso.",
      ".ohbmlttmtmbbso.",
      ".ohbmmmmmmmbbso.",
      ".ohbbbbbbbbbbso.",
      ".ohbbbbbbbbbbso.",
      ".ohbwwwwwwwwbso.",
      ".ohbwwwwwwwwbso.",
      ".ohbwmmmmmmwbso.",
      ".ohbwwwwwwwwbso.",
      ".ohbwmmmmwwwbso.",
      ".osssssssssssso.",
      "..oooooooooooo..",
      "................",
    ],
  },
};

const SIZE = 16;
const SVG = "http://www.w3.org/2000/svg";

function colour(name) {
  const [ramp, shade] = name.split(".");
  return shade === undefined ? PALETTE[ramp] : PALETTE[ramp]?.[Number(shade)];
}

// What's wrong with a sprite, if anything: rows of the wrong length, or a letter with no
// colour. A hand-drawn sprite is easy to get one letter off.
export function problems({ key, rows }) {
  const found = [];
  if (rows.length !== SIZE) found.push(`${rows.length} rows, not ${SIZE}`);
  rows.forEach((row, y) => {
    if (row.length !== SIZE) found.push(`row ${y} is ${row.length} wide, not ${SIZE}`);
    for (const letter of row) {
      if (letter !== "." && !colour(key[letter] ?? "")) found.push(`row ${y}: "${letter}" has no colour`);
    }
  });
  return [...new Set(found)];
}

// The kind an icon is looked up by: a build, or the ID's prefix (BAT-12 → BAT).
export const kindOf = (node) => (node.group === "build" ? "build" : node.id.split("-")[0]);

// A palette swap (lesson 3): the sprite's main ramp (its base colour's) becomes `colour`'s.
// The drawing stays; details in other ramps (a bolt, a nub) keep theirs.
function swapped(sprite, swap) {
  const main = sprite?.key.b?.split(".")[0];
  if (!swap || !main || !PALETTE[swap]) return sprite;
  const key = Object.fromEntries(Object.entries(sprite.key).map(([letter, name]) =>
    [letter, name.startsWith(`${main}.`) ? name.replace(main, swap) : name]));
  return { ...sprite, key };
}

// An <svg> for this kind (swapped to `swap`, a ramp name, if given), one path per colour. No sprite: `fallback`'s,
// else a tile with the kind's letters, so a new kind still gets something.
export function icon(kind, swap = null, fallback = null) {
  const sprite = swapped(SPRITES[kind] ?? SPRITES[fallback], swap);
  const broken = sprite && problems(sprite);
  if (broken?.length) console.warn(`icons.js: ${kind}: ${broken.join("; ")}`);
  if (!sprite || broken.length) {
    const tile = document.createElement("span");
    tile.className = "icon tile";
    tile.textContent = kind.slice(0, 3);
    tile.setAttribute("aria-hidden", "true");
    return tile;
  }
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("class", "icon");
  svg.setAttribute("viewBox", `0 0 ${SIZE} ${SIZE}`);
  svg.setAttribute("shape-rendering", "crispEdges");
  svg.setAttribute("aria-hidden", "true");            // the ID beside it says what it is
  const paths = new Map();
  sprite.rows.forEach((row, y) => [...row].forEach((letter, x) => {
    if (letter === ".") return;
    const fill = colour(sprite.key[letter]);
    paths.set(fill, (paths.get(fill) ?? "") + `M${x} ${y}h1v1h-1z`);
  }));
  for (const [fill, d] of paths) {
    const path = document.createElementNS(SVG, "path");
    path.setAttribute("fill", fill);
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}
