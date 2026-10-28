// The readback after a write ("✓ BAT-12 · Blue 6S · was in Case A → van") with its Undo,
// or why nothing was logged. The readback is how a wrong ID gets caught, so it stays a while.
import { button, el } from "./dom.js";

export const css = `
.toasts {
  position: fixed;
  right: var(--space);
  bottom: var(--space);
  left: var(--space);
  z-index: 10;
  display: grid;
  gap: calc(var(--space) / 2);
  justify-items: center;
  pointer-events: none;
}
.toast {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space);
  width: min(36rem, 100%);
  padding: calc(var(--space) / 2) var(--space);
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--line);
  border-left: 6px solid var(--ok);
  border-radius: var(--radius);
  box-shadow: 0 4px 16px rgb(0 0 0 / 0.2);
  pointer-events: auto;
}
.toast.error { border-left-color: var(--error); }
.toast p { flex: 1; margin: 0; }
.toast small { display: block; color: var(--muted); }
`;

export function toast(text, { error = false, messages = [], onUndo = null } = {}) {
  const node = el("div", error ? "toast error" : "toast");
  node.setAttribute("role", error ? "alert" : "status");
  const line = el("p", "", text);
  for (const message of messages) line.append(el("small", "", message));
  node.append(line);
  if (onUndo) node.append(button("Undo", "", () => { node.remove(); onUndo(); }));
  node.append(button("×", "", () => node.remove()));
  return node;
}
