/* 外殻はキャッシュ優先、データはネットワーク優先。
   圏外でも直近に開いた内容が読める状態を保つのが目的。 */

// 見た目を作り替えたら必ず上げること。上げないと端末に古い外殻が残り続ける。
const VERSION = "v10";
const SHELL = `shell-${VERSION}`;
const DATA = `data-${VERSION}`;

const SHELL_FILES = [
  "./",
  "index.html",
  "style.css",
  "app.js",
  "manifest.webmanifest",
  "icon-192.png",
  "icon-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(SHELL)
      .then((c) => c.addAll(SHELL_FILES))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== SHELL && k !== DATA).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // 台帳データ: 新しいものを優先し、取れなければ最後に取れたものを出す
  if (url.pathname.includes("/data/")) {
    e.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(DATA).then((c) => c.put(req, copy));
          return res;
        })
        .catch(() => caches.match(req).then((hit) => hit || Response.error()))
    );
    return;
  }

  // 外殻: キャッシュを先に返しつつ裏で更新する
  e.respondWith(
    caches.match(req).then((hit) => {
      const net = fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(SHELL).then((c) => c.put(req, copy));
          return res;
        })
        .catch(() => hit);
      return hit || net;
    })
  );
});
