// Service Worker do TMP10 — permite notificações push mesmo com o site fechado

self.addEventListener('push', function (event) {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { title: 'TMP10', body: event.data ? event.data.text() : 'Nova notificação' };
  }

  const title = data.title || '🔔 TMP10';
  const options = {
    body: data.body || '',
    tag: data.tag || 'tmp10-notificacao',
    vibrate: [200, 100, 200, 100, 200],
    requireInteraction: true,
    renotify: true
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (clientList) {
      for (const client of clientList) {
        if ('focus' in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow('/');
    })
  );
});

self.addEventListener('install', function (event) {
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(clients.claim());
});
