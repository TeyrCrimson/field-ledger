// Lets the board open with no hub. Browsers only run this on a secure page (HTTPS, or this
// laptop's own 127.0.0.1), which is why phones join the hub by QR code (setup.html).
//
// Network first, so a hub that's there always wins, and the last copy when it isn't. Every
// board file is saved when the worker installs (the hub lists them, whatever a design pass
// adds), so one visit with the hub is enough. A saved answer says so in a header, so the
// board never claims "Updated" for an old copy.
const CACHE = "board";

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const files = await (await fetch("web-files.json", { cache: "no-store" })).json();
    await (await caches.open(CACHE)).addAll(["./", "state.json", ...files]);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  if (event.request.method === "GET") event.respondWith(fromHub(event.request));
});

async function fromHub(request) {
  try {
    const response = await fetch(request);
    if (response.ok) (await caches.open(CACHE)).put(request, response.clone());
    return response;
  } catch (error) {
    const saved = await caches.match(request);
    if (!saved) throw error;
    const headers = new Headers(saved.headers);
    headers.set("X-Saved-Copy", "1");
    return new Response(saved.body, { status: saved.status, headers });
  }
}
