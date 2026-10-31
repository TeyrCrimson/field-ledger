// Lets the board open with no hub. Browsers only run this on a secure page (HTTPS, or this
// laptop's own 127.0.0.1), which is why phones join the hub by QR code (setup.html).
//
// The kit (state.json) is network first, so a hub that's there always wins, and the last copy
// when it isn't. The board's own files are the saved copy at once, refreshed for next time:
// with Wi-Fi off and mobile data on, a request to the hub hangs instead of failing, and the
// page, its script and each component waited their turn for it. Every board file is saved
// when the worker installs (the hub lists them, whatever a design pass adds), so one visit
// with the hub is enough. A saved answer says so in a header, so the board never claims
// "Updated" for an old copy.
// Opening at once means an update shows on the next open, not this one, so a refresh that
// brings a board file different from the saved one tells the page, which offers a reload
// (board.js). It never reloads itself: that could land mid-drag.
const CACHE = "board";
const HUB_MS = 1_500;      // under api.js's 3 s, so a hanging hub still gets the board its saved kit

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const files = await (await fetch("web-files.json", { cache: "no-store" })).json();
    await (await caches.open(CACHE)).addAll(["./", "state.json", ...files]);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const fresh = fromHub(request);
  if (new URL(request.url).pathname.endsWith("/state.json")) return event.respondWith(fresh);
  event.waitUntil(fresh.catch(() => {}));
  event.respondWith(caches.match(request).then((saved) => saved || fresh));
});

async function fromHub(request) {
  try {
    const response = await fetch(request, { signal: AbortSignal.timeout(HUB_MS) });
    if (response.ok) {
      const saved = await caches.match(request);
      const [keep, check] = [response.clone(), response.clone()];
      await (await caches.open(CACHE)).put(request, keep);
      const kit = new URL(request.url).pathname.endsWith("/state.json");
      if (saved && !kit && await saved.text() !== await check.text()) {
        for (const client of await self.clients.matchAll()) client.postMessage("updated");
      }
    }
    return response;
  } catch (error) {
    const saved = await caches.match(request);
    if (!saved) throw error;
    const headers = new Headers(saved.headers);
    headers.set("X-Saved-Copy", "1");
    return new Response(saved.body, { status: saved.status, headers });
  }
}
