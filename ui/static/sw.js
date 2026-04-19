// Karma Service Worker — offline-first with network fallback
const CACHE = "karma-v1";
const OFFLINE_ASSETS = [
  "/mobile",
  "/static/mobile.css",
  "/static/mobile.js",
  "/static/manifest.json",
];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(OFFLINE_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);

  // API calls: network-first, cache fallback
  if (url.pathname.startsWith("/api/")) {
    e.respondWith(
      fetch(e.request)
        .then(resp => {
          // Cache GET API responses for offline use
          if (e.request.method === "GET" && resp.ok) {
            const clone = resp.clone();
            caches.open(CACHE).then(c => c.put(e.request, clone));
          }
          return resp;
        })
        .catch(() => caches.match(e.request).then(r => r || new Response(
          JSON.stringify({error: "offline", cached: false}),
          {headers: {"Content-Type": "application/json"}}
        )))
    );
    return;
  }

  // Static assets: cache-first
  e.respondWith(
    caches.match(e.request).then(r => r || fetch(e.request).then(resp => {
      if (resp.ok) {
        const clone = resp.clone();
        caches.open(CACHE).then(c => c.put(e.request, clone));
      }
      return resp;
    }))
  );
});
