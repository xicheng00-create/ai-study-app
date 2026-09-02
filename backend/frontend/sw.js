/* ServiceWorker：network-first App Shell（联网必拿最新，离线回退缓存） */
/* v3：修复 cache-first 导致部署后用户永远看到旧版的问题；bump 以强制旧缓存失效 */
const CACHE = "aistudy-shell-v3";
const ASSETS = ["/", "/css/style.css", "/js/api.js", "/js/app.js", "/js/student.js", "/js/teacher.js", "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  // API 与上传走网络，不缓存
  if (url.pathname.startsWith("/api/")) return;
  if (e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request).then((resp) => {
      const copy = resp.clone();
      caches.open(CACHE).then((c) => c.put(e.request, copy));
      return resp;
    }).catch(() => caches.match(e.request).then((c) => c || caches.match("/")))
  );
});
