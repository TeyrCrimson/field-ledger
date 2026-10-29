// The phone's side of "Add a phone", opened from the QR code on the laptop. It's plain http,
// because the phone doesn't trust the hub yet. Three steps, like linking WhatsApp: get the
// hub's certificate, trust it in the phone's Settings (a web page isn't allowed to do that
// part), and a check that turns green by itself once the phone trusts the hub. Then the
// board over HTTPS, which keeps working with no hub.
import { el } from "./components/dom.js";

const CHECK_MS = 2_000;

const css = `
.setup { max-width: 34rem; margin: 0 auto; padding: var(--space) var(--space) 3rem; }
.setup h1 { margin: var(--space) 0 0.25rem; font-size: 1.6rem; }
.setup .lead { margin: 0 0 var(--space); color: var(--muted); }
.setup .step {
  display: grid;
  grid-template-columns: 2.5rem 1fr;
  gap: var(--space);
  margin: calc(var(--space) + 3 * var(--px)) calc(2 * var(--px)) 0;
  padding: var(--space);
  background: var(--surface);
  box-shadow: var(--frame);
}
.setup .number {
  display: grid;
  place-items: center;
  width: 2.5rem;
  height: 2.5rem;
  color: var(--on-accent);
  background: var(--trim);
  box-shadow: inset calc(-1 * var(--px)) calc(-1 * var(--px)) 0 rgb(0 0 0 / 0.25);
  font-family: var(--pixel);
  font-size: 1.2rem;
  font-weight: 700;
}
.setup .step.done .number { background: var(--ok); }
.setup .step.done { --trim: var(--ok); }
.setup h2 { margin: 0.4rem 0 0.25rem; font-size: 1.05rem; }
.setup p, .setup li { margin: 0.25rem 0; line-height: 1.4; }
.setup ol { margin: 0.25rem 0; padding-left: 1.2em; }
.setup .hint { color: var(--muted); font-size: 0.875rem; }
.setup .go {
  display: inline-flex;
  align-items: center;
  min-height: var(--tap);
  margin-top: 0.5rem;
  padding: 0 calc(var(--space) * 1.5);
  color: var(--on-accent);
  background: var(--accent);
  box-shadow: 0 calc(-1 * var(--px)) 0 var(--outline), 0 var(--px) 0 var(--outline),
              calc(-1 * var(--px)) 0 0 var(--outline), var(--px) 0 0 var(--outline);
  font-family: var(--pixel);
  font-weight: 600;
  text-decoration: none;
}
.setup .status { font-weight: 600; }
.setup .status.waiting::before { content: "⏳ "; }
.setup .status.ok { color: var(--ok); }
.setup details { margin-top: calc(var(--space) * 2); color: var(--muted); }
.setup summary { min-height: var(--tap); line-height: var(--tap); cursor: pointer; }
`;

const PHONES = {
  android: {
    label: "Android",
    get: "Tap the button. If the phone says the certificate must be installed in Settings, " +
         "that's expected: go on to step 2.",
    trust: ["Open Settings and search for CA certificate.",
            "Tap it, then Install anyway.",
            "Pick field-ledger-hub.crt (in Downloads)."],
    hint: "Samsung: Settings → Security and privacy → More security settings → " +
          "Install from device storage → CA certificate.",
    remove: "Settings → search for User credentials → tap the old one → Remove.",
    home: "Then in Chrome: ⋮ → Add to Home screen.",
  },
  iphone: {
    label: "iPhone",
    get: "Tap the button, then Allow. The phone says Profile Downloaded.",
    trust: ["Open Settings → Profile Downloaded → Install (it asks for your passcode).",
            "Then Settings → General → About → Certificate Trust Settings.",
            "Turn on the switch for the field-ledger hub."],
    hint: "",
    remove: "Settings → General → VPN & Device Management → tap the old one → Remove Profile.",
    home: "Then in Safari: Share → Add to Home Screen.",
  },
};

function whichPhone() {
  const agent = navigator.userAgent;
  if (/android/i.test(agent)) return ["android"];
  if (/iphone|ipad|ipod/i.test(agent) || (/macintosh/i.test(agent) && navigator.maxTouchPoints > 1)) {
    return ["iphone"];
  }
  return ["android", "iphone"];                 // can't tell: show both
}

function step(number, title, ...body) {
  const card = el("section", "step");
  const text = el("div", "");
  text.append(el("h2", "", title), ...body);
  card.append(el("span", "number", String(number)), text);
  return card;
}

function list(items) {
  const ol = el("ol", "");
  for (const item of items) ol.append(el("li", "", item));
  return ol;
}

function link(text, href, download = false) {
  const a = Object.assign(el("a", "go", text), { href });
  if (download) a.download = "field-ledger-hub.crt";
  return a;
}

// The phone trusts the hub once an HTTPS request to it gets through. no-cors: only whether it
// connected matters, and an untrusted certificate fails it.
async function trusted(board) {
  try {
    await fetch(`${board}web-files.json`, { mode: "no-cors", cache: "no-store" });
    return true;
  } catch {
    return false;
  }
}

async function main() {
  const style = document.createElement("style");
  style.textContent = css;
  document.head.append(style);
  const setup = await fetch("phone-setup.json").then((r) => (r.ok ? r.json() : {})).catch(() => ({}));
  const board = `https://${location.host}/`;
  const phones = whichPhone().map((kind) => PHONES[kind]);
  const both = phones.length > 1;
  const per = (key) => phones.flatMap((p) => (p[key] ? [el("p", "hint", both ? `${p.label}: ${p[key]}` : p[key])] : []));

  const status = el("p", "status waiting", "Waiting for step 2…");
  const done = el("div", "");
  const check = step(3, "Check", status, done);
  const page = document.getElementById("setup");
  page.append(
    el("h1", "", "Add this phone to the hub"),
    el("p", "lead", "About a minute, once per phone. Then the board works here even when the hub is away."),
    step(1, "Get the hub's certificate", link("Get the certificate", "/ca.crt", true), ...per("get")),
    step(2, "Trust it in Settings",
         ...phones.flatMap((p) => [...(both ? [el("p", "", p.label)] : []), list(p.trust)]),
         ...per("hint")),
    check,
  );
  if (setup.ca_name) {
    const old = el("details", "");
    old.append(el("summary", "", "Set up for another hub before?"),
               el("p", "", `This hub's certificate is called “${setup.ca_name}”. Any other ` +
                           "field-ledger hub certificate on this phone is from an old hub and can go:"),
               ...per("remove"));
    page.append(old);
  }

  while (!(await trusted(board))) await new Promise((r) => setTimeout(r, CHECK_MS));
  check.classList.add("done");
  status.className = "status ok";
  status.textContent = "✓ This phone trusts the hub.";
  done.append(link("Open the board", board), ...per("home"));
}

main();
