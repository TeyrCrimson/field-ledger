// "Send through Telegram": when this phone can't reach the hub but has internet, its waiting
// writes go to the team's bot as messages, and the hub logs them when it next has internet.
// Each write is a readable line, then `#fl` and the JSON the phone would have sent the hub,
// with its own id, time and seq: logged once however often it's sent, in the order it was
// tapped. The writes stay waiting here too, and the hub answers "already logged" later.
import { button, describeWrite, el } from "./dom.js";

const LIMIT = 3500;                      // a Telegram message holds 4096 characters

export const css = `
.relay textarea { width: 100%; min-height: 8rem; font-family: var(--mono); font-size: 0.75rem; }
.relay .row { display: flex; flex-wrap: wrap; gap: calc(var(--space) / 2); margin: calc(var(--space) / 2) 0 var(--space); }
`;

// The waiting writes as messages, each short enough to send. A write never splits.
export function relayMessages(waiting) {
  const messages = [];
  let current = "";
  for (const { command, body } of waiting) {
    const part = `${describeWrite(command, body)}\n#fl ${JSON.stringify({ command, body })}\n`;
    if (current && current.length + part.length > LIMIT) {
      messages.push(current);
      current = "";
    }
    current += part;
  }
  return current ? [...messages, current] : messages;
}

async function copy(text, area) {
  try {
    await navigator.clipboard.writeText(text);         // only on a secure page
  } catch {
    area.select();
    document.execCommand?.("copy");                     // plain http: the old way
  }
}

export function relayDialog(bot, waiting) {
  const dialog = el("dialog", "relay");
  const messages = relayMessages(waiting);
  dialog.append(el("h2", "", "Send through Telegram"),
                el("p", "hint", `The hub is away. Copy ${messages.length > 1 ? "each message" : "this"}, `
                                + `open @${bot}, paste and send. The hub logs ${waiting.length} `
                                + "write(s) when it next has internet; each counts once."));
  messages.forEach((text, n) => {
    const area = el("textarea", "");
    area.readOnly = true;
    area.value = text;
    const row = el("div", "row");
    row.append(button(messages.length > 1 ? `Copy part ${n + 1} of ${messages.length}` : "Copy",
                      "primary", () => copy(text, area)));
    dialog.append(area, row);
  });
  const row = el("div", "row");
  row.append(button(`Open @${bot}`, "", () => window.open(`https://t.me/${bot}`, "_blank", "noopener")),
             button("Close", "", () => dialog.close()));
  dialog.append(row);
  return dialog;
}
