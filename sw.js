// 네트워크 우선, 실패하면(오프라인) 마지막으로 받아둔 화면을 보여준다.
const CACHE = "jnu-alerts-v1";

self.addEventListener("install", () => self.skipWaiting());

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
  // 페이지 자체는 브라우저 HTTP 캐시를 건너뛰고 항상 최신 수집본을 확인
  const fresh = req.mode === "navigate" ? fetch(req, { cache: "no-cache" }) : fetch(req);
  e.respondWith(
    fresh
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req, { ignoreSearch: true }).then((hit) => hit || caches.match("./")))
  );
});
