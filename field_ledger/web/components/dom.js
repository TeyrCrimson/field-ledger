// Helpers the components share: an element with a class and some text, and a button.
export function el(tag, className, text = "") {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}

export function button(text, className = "", onClick = null) {
  const node = el("button", className, text);
  node.type = "button";
  if (onClick) node.addEventListener("click", onClick);
  return node;
}

// Shared look for every dialog, so each dialog component only styles its own inside.
export const dialogCss = `
dialog {
  width: min(28rem, calc(100vw - 2 * var(--space)));
  padding: calc(var(--space) * 1.5);
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
dialog::backdrop { background: rgb(0 0 0 / 0.45); }
dialog h2 { margin: 0 0 var(--space); font-size: 1.1rem; }
dialog .row { display: flex; flex-wrap: wrap; gap: calc(var(--space) / 2); margin-top: var(--space); }
dialog label { display: grid; gap: 0.25rem; margin-top: var(--space); font-size: 0.875rem; }
dialog input {
  min-height: var(--tap);
  padding: 0 var(--space);
  font: inherit;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}
button {
  min-height: var(--tap);
  padding: 0 var(--space);
  font: inherit;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  cursor: pointer;
}
button.primary { color: var(--on-accent); background: var(--accent); border-color: var(--accent); }
`;
