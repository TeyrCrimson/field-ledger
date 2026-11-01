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

// One line for a write that hasn't been logged yet (waiting, or needing a look).
export function describeWrite(command, body) {
  switch (command) {
    case "move": return `${body.item} → ${body.to}`;
    case "add": return `+${body.count} ${String(body.prefix).toUpperCase()} at ${body.at}`;
    case "label": return `${body.build}: label ${String(body.label).toUpperCase()}`;
    case "state": return `${body.item}: ${body.state}`;
    case "audit": return `${body.item}: ${!body.found ? "checked" : body.found === "lost" ? "missing" : `found in ${body.found}`}`;
    case "resolve": return `${body.item} is in ${body.to}`;
    default: return command;
  }
}

// Shared look for every dialog and button, so each component only styles its own inside.
// A dialog is a pixel window; a button is a smaller one that sinks a pixel when pressed.
export const dialogCss = `
dialog {
  width: min(28rem, calc(100vw - 2 * var(--space) - 4 * var(--px)));
  padding: calc(var(--space) * 1.5);
  color: var(--text);
  background: var(--surface);
  border: 0;
  border-radius: var(--radius);
  box-shadow: var(--frame);
}
dialog::backdrop { background: rgb(0 0 0 / 0.45); }
dialog h2 { margin: 0 0 var(--space); font-size: 1.25rem; }
dialog .row { display: flex; flex-wrap: wrap; gap: var(--space); margin-top: calc(var(--space) * 1.5); }
dialog label { display: grid; gap: 0.25rem; margin-top: var(--space); font-size: 0.875rem; }
dialog input, .actionbar input {
  min-height: var(--tap);
  margin: var(--px);
  padding: 0 var(--space);
  font: inherit;
  color: var(--text);
  background: var(--surface);
  border: 0;
  border-radius: var(--radius);
  box-shadow: var(--frame-thin);
}
dialog input:focus, .actionbar input:focus { outline: var(--px) solid var(--trim); outline-offset: var(--px); }
button {
  min-height: var(--tap);
  margin: var(--px);
  padding: 0 var(--space);
  font-size: 1rem;
  font-weight: 600;
  color: var(--text);
  background: var(--surface);
  border: 0;
  border-radius: var(--radius);
  box-shadow: var(--frame-thin);
  cursor: pointer;
}
button .icon { width: 16px; height: 16px; margin-right: 0.4em; vertical-align: -2px; }
button:active { transform: translateY(var(--px)); box-shadow: var(--frame-thin), inset 0 var(--px) 0 var(--surface-2); }
button:focus-visible { outline: var(--px) solid var(--trim); outline-offset: calc(2 * var(--px)); }
button.primary { color: var(--on-accent); background: var(--accent); }
button.primary { box-shadow: 0 calc(-1 * var(--px)) 0 var(--outline), 0 var(--px) 0 var(--outline),
                 calc(-1 * var(--px)) 0 0 var(--outline), var(--px) 0 0 var(--outline),
                 inset calc(-1 * var(--px)) calc(-1 * var(--px)) 0 rgb(0 0 0 / 0.25); }
`;
