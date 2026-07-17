// Minimal service worker — just enough to satisfy Chrome's "installable app"
// requirement (a registered service worker with a fetch handler).
// It does not cache anything, so the app always loads fresh data.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
