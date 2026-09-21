// App-shell cache only. The API (/api/*) and the legacy pages are never cached: live data and
// the controller must always come from the bridge, and a cached "logged in" view would be wrong.
const CACHE = "sunshare-shell-v1";
const SHELL = ["/app/", "/app/manifest.webmanifest", "/app/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== location.origin || !url.pathname.startsWith("/app/")) return;

  if (url.pathname.startsWith("/app/assets/")) {
    // Hashed build files never change: cache first.
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
        return res;
      })),
    );
  } else if (req.mode === "navigate") {
    // The shell: network first so a new release shows up, cached copy when offline.
    event.respondWith(fetch(req).catch(() => caches.match("/app/")));
  }
});
