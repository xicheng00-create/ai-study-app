/* ServiceWorker：network-first App Shell（联网必拿最新，离线回退缓存） */
/* v43：v2.4.0 每日打卡连胜 + 通知中心 + Web Push（push/notificationclick），bump 以强制旧缓存失效 */
/* v46：v2.6.0 教师端知识卡片核查页（课程页入口 + 章/主题/卡片钻取），bump 以强制旧缓存失效 */
/* v48：v2.6.3 每日任务卡片阈值 10→30（阈值改由后端下发，前端不再硬编码）+ 进度不回退（消除「4/10 卡却显示已完成」） */
/* v49：v2.6.4 单次复习卡组上限 100 张（deck_max 后端下发）+ 待复习不再含未学卡 + AI 建议按钮由 can_generate 决定/窗口覆盖昨天到今天 */
const CACHE = "aistudy-shell-v50";
/* 预缓存 URL 必须与 index.html 里的 ?v= 同版（CF 对 .js/.css 强制 4h 浏览器缓存，换 URL 才能穿透） */
const V = "2.6.5";
const ASSETS = ["/", `/css/style.css?v=${V}`, `/js/api.js?v=${V}`, `/js/app.js?v=${V}`, `/js/student.js?v=${V}`, `/js/teacher.js?v=${V}`, "/manifest.webmanifest"];

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
/* Web Push（NOTIF-002）：后台收到推送 → 系统通知；点开 → 打开对应页 */
self.addEventListener("push", (e) => {
  let payload = {};
  try { payload = e.data ? e.data.json() : {}; } catch (err) { payload = {}; }
  const title = payload.title || "AI 学习小组";
  const opts = {
    body: payload.body || "",
    icon: payload.icon || "/icon-192.png",
    badge: payload.badge || "/img/notify/notify-badge.png",
    data: payload.data || { url: "/" },
  };
  if (payload.image) opts.image = payload.image;
  e.waitUntil(self.registration.showNotification(title, opts));
});
self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const c of list) {
        if (c.navigate) { c.navigate(url); c.focus(); return; }
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
