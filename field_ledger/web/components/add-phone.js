// "Add a phone", the way you link WhatsApp to a computer: a QR code on the laptop that the
// phone's camera opens; the phone walks through the rest itself (setup.html). The hub sends
// the code as rows of 0s and 1s, and this draws them.
import { button, el } from "./dom.js";

export const css = `
.add-phone { text-align: center; }
.add-phone svg {
  display: block;
  width: min(18rem, 70vw);
  height: auto;
  margin: var(--space) auto;
  background: var(--qr-light);
  border-radius: var(--radius);
}
.add-phone ol { max-width: 20rem; margin: 0 auto; padding-left: 1.4em; text-align: left; }
.add-phone li { margin: 0.4em 0; }
.add-phone .url { color: var(--muted); font-family: var(--mono); font-size: 0.875rem; word-break: break-all; }
`;

const SVG = "http://www.w3.org/2000/svg";

function qrCode(rows) {
  const size = rows.length + 8;                         // 4 light modules all round
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("viewBox", `0 0 ${size} ${size}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "QR code to add a phone");
  svg.setAttribute("shape-rendering", "crispEdges");
  const path = document.createElementNS(SVG, "path");
  path.setAttribute("fill", "var(--qr-dark)");
  path.setAttribute("d", rows.flatMap((row, y) => [...row].map((module, x) =>
    module === "1" ? `M${x + 4} ${y + 4}h1v1h-1z` : "")).join(""));
  svg.append(path);
  return svg;
}

export function addPhoneDialog({ url, qr }) {
  const dialog = el("dialog", "add-phone");
  const steps = el("ol", "");
  for (const step of ["Open the phone's camera.",
                      "Point it at this code and tap the link it shows.",
                      "Follow the steps on the phone. About a minute, once per phone."]) {
    steps.append(el("li", "", step));
  }
  const row = el("div", "row");
  row.append(button("Done", "primary", () => dialog.close()));
  dialog.append(el("h2", "", "Add a phone"), qrCode(qr), steps, el("p", "url", `Or type ${url}`), row);
  return dialog;
}
