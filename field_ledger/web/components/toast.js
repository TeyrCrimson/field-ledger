// The readback after a write ("✓ BAT-12 · Blue 6S · was in Case A → van") with its Undo,
// or why nothing was logged. The readback is how a wrong ID gets caught, so it stays a while.
//
// A text box at the bottom, as in a handheld RPG: the text types out (very fast), then a ▼
// says it's all there. Tap it while it types to show the rest at once; tap again to put it
// away. The tap is the only close (no ×, Teyr 2026-10-30); a keyboard focuses the box and
// presses Enter or Space. At most three are on screen; the next waits and shows when one is
// tapped away, so a burst of writes never buries the board.
import { button, el } from "./dom.js";

const SHOWN = 3;
const CHARS_PER_FRAME = 2;                              // "very fast": about 120 a second

export const css = `
.toasts {
  position: fixed;
  right: var(--space);
  bottom: calc(var(--space) + 2 * var(--px));
  left: var(--space);
  z-index: 10;
  display: grid;
  gap: calc(var(--space) + 4 * var(--px));
  justify-items: center;
  pointer-events: none;
}
.toast {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space);
  width: min(36rem, calc(100% - 4 * var(--px)));
  min-height: 4rem;
  padding: var(--space) calc(var(--space) * 1.25) calc(var(--space) * 1.6);
  color: var(--text);
  background: var(--surface);
  box-shadow: var(--frame);
  font-size: 1.05rem;
  line-height: 1.4;
  cursor: pointer;
  pointer-events: auto;
}
.toast.error { --trim: var(--error); }
.toast p { flex: 1; margin: 0; }
.toast small { display: block; color: var(--muted); font-size: 0.875rem; }
.toast .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
.toast button { min-height: 36px; }
/* ▼, blinking, once the whole text is there. 7×4 pixels, stepped like the ▶ pointer. */
.toast.done::after {
  content: "";
  position: absolute;
  right: calc(var(--space) * 0.6);
  bottom: calc(var(--space) * 0.4);
  width: 14px;
  height: 8px;
  background: var(--accent);
  clip-path: polygon(0 0, 100% 0, 100% 25%, 85.7% 25%, 85.7% 50%, 71.4% 50%, 71.4% 75%,
                     57.1% 75%, 57.1% 100%, 42.9% 100%, 42.9% 75%, 28.6% 75%, 28.6% 50%,
                     14.3% 50%, 14.3% 25%, 0 25%);
  animation: more 0.8s steps(1) infinite;
}
@keyframes more { 50% { opacity: 0; } }
`;

export function toast(text, { error = false, messages = [], onUndo = null } = {}) {
  const node = el("div", error ? "toast error" : "toast");
  node.setAttribute("role", error ? "alert" : "status");
  const line = el("p", "");
  const typed = el("span", "");
  typed.setAttribute("aria-hidden", "true");          // a screen reader gets the whole text
  const notes = messages.map((message) => el("small", "", message));
  line.append(el("span", "sr", [text, ...messages].join(" ")), typed);
  node.append(line);
  if (onUndo) node.append(button("Undo", "", () => { node.dismiss(); onUndo(); }));
  node.tabIndex = 0;
  node.dismiss = () => node.remove();                 // until show() takes it over

  let shown = 0;
  const finish = () => {
    shown = text.length;
    typed.textContent = text;
    typed.append(...notes);
    node.classList.add("done");
  };
  node.start = () => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) return finish();
    const step = () => {
      if (shown >= text.length) return;               // finished by a tap
      shown += CHARS_PER_FRAME;
      if (shown >= text.length) return finish();
      typed.textContent = text.slice(0, shown);
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };
  node.addEventListener("click", (event) => {
    if (event.target.closest("button")) return;
    if (node.classList.contains("done")) node.dismiss();
    else finish();
  });
  node.addEventListener("keydown", (event) => {
    if (event.target !== node || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();                           // Space would scroll the board
    node.click();
  });
  return node;
}

// Show a toast in `box`, or queue it behind the three already there. It stays `ms` from
// when it shows, not from when it was made. dismiss() takes it away (or out of the queue)
// and lets the next one in.
const queue = [];

export function show(box, node, ms) {
  const put = (next) => {
    box.append(next);
    next.start();
    next.timer = setTimeout(() => next.dismiss(), ms);
  };
  node.dismiss = () => {
    const waiting = queue.indexOf(node);
    if (waiting >= 0) return void queue.splice(waiting, 1);
    if (!node.isConnected) return;
    clearTimeout(node.timer);
    node.remove();
    if (queue.length) put(queue.shift());
  };
  if (box.childElementCount < SHOWN) put(node);
  else queue.push(node);
  return node;
}
