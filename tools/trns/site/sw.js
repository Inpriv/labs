/* trns site service worker: offline-first app shell, network-first for the page. */
const CACHE = "trns-site-v1";
const SHELL = ["./", "index.html", "manifest.webmanifest", "icon.svg",
               "icon-192.png", "icon-512.png", "apple-touch-icon.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET" || new URL(req.url).origin !== location.origin) return;
  const isPage = req.mode === "navigate";
  e.respondWith(
    isPage
      ? fetch(req).then((r) => { caches.open(CACHE).then((c) => c.put(req, r.clone())); return r; })
          .catch(() => caches.match(req).then((r) => r || caches.match("index.html")))
      : caches.match(req).then((r) => r || fetch(req).then((n) => {
          caches.open(CACHE).then((c) => c.put(req, n.clone())); return n;
        }))
  );
});
