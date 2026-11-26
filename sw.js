// Ski Days offline worker: the app opens with no signal and shows the last snow and weather it saw.
const CACHE = 'skidays-v1';
const SHELL = ['./', 'index.html', 'manifest.webmanifest', 'images/hero.jpg', 'icons/icon-192.png', 'icons/icon-512.png', 'icons/icon-180.png'];
self.addEventListener('install', e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
const fresh = async req => {   // network first, so updates and new snow reports show at once; the saved copy when offline
  try { const r = await fetch(req); if (r && (r.ok || r.type === 'opaque') && req.method === 'GET') { const c = await caches.open(CACHE); c.put(req, r.clone()); } return r; }
  catch (e) { const hit = await caches.match(req, {ignoreSearch: true}); if (hit) return hit; if (req.mode === 'navigate') return caches.match('index.html'); throw e; }
};
const saved = async req => {   // pictures, icons and fonts: the saved copy first
  const hit = await caches.match(req); if (hit) return hit;
  const r = await fetch(req); if (r && (r.ok || r.type === 'opaque')) { const c = await caches.open(CACHE); c.put(req, r.clone()); } return r;
};
self.addEventListener('fetch', e => {
  const req = e.request; if (req.method !== 'GET') return;
  const u = new URL(req.url);
  if (/\.(png|jpe?g|webp|svg|woff2?)$/.test(u.pathname) || u.hostname.endsWith('gstatic.com')) { e.respondWith(saved(req)); return; }
  if (u.origin === location.origin || /open-meteo\.com|avalanche\.ca|fonts\.googleapis\.com/.test(u.hostname)) { e.respondWith(fresh(req)); return; }
});
