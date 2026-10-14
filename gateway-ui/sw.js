// Notification-only worker. It never caches or intercepts iCloud file requests.
self.addEventListener('push', event => {
 let message={title:'iCloud 网关提醒',body:'请打开私有网关查看状态。',tag:'icloud-gateway-health'};
 try{Object.assign(message,event.data.json())}catch{}
 event.waitUntil(self.registration.showNotification(message.title,{body:message.body,tag:message.tag,data:{url:'/'}}));
});
self.addEventListener('notificationclick', event => {
 event.notification.close();
 event.waitUntil(self.clients.matchAll({type:'window',includeUncontrolled:true}).then(windows=>{
  const existing=windows.find(w=>new URL(w.url).origin===self.location.origin);
  return existing?existing.focus():self.clients.openWindow('/');
 }));
});
