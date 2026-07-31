// TraderIA WIN — service worker mínimo.
// Não faz cache de nada de propósito: este painel exibe dados de mercado
// e decisões em tempo (quase) real, então cache agressivo faria mais mal
// que bem. Existe apenas para satisfazer o requisito de PWA/instalação.

self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  // Passthrough puro — sempre busca da rede, nunca do cache.
  event.respondWith(fetch(event.request));
});
