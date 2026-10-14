"""Private Web Push state and deduplicated authentication alerts. Python 3.6+."""
import base64,datetime,hashlib,json,os,pathlib,subprocess,threading,time,urllib.parse,uuid
STATUSES={'OK','REAUTH_REQUIRED','APPLE_WEB_ACCESS_DISABLED','REGION_INCOMPATIBLE','CHECK_FAILED','NETWORK_TIMEOUT'}

def valid_subscription(s):
 if not isinstance(s,dict):raise ValueError('subscription required')
 endpoint=s.get('endpoint','');u=urllib.parse.urlsplit(endpoint);host=(u.hostname or '').lower()
 if u.scheme!='https' or u.username or u.password or u.fragment or u.port not in (None,443) or len(endpoint)>8192:raise ValueError('invalid push endpoint')
 if not (host.endswith('.push.apple.com') or host in ('fcm.googleapis.com','updates.push.services.mozilla.com')):raise ValueError('unsupported push provider')
 keys=s.get('keys',{})
 for name,length in [('p256dh',65),('auth',16)]:
  value=keys.get(name,'')
  if not isinstance(value,str) or len(value)>100:raise ValueError('invalid push key')
  try:b=base64.urlsafe_b64decode(value+'='*((-len(value))%4))
  except Exception:raise ValueError('invalid push key')
  if len(b)!=length or name=='p256dh' and b[0]!=4:raise ValueError('invalid push key')
 return {'endpoint':endpoint,'keys':{k:keys[k] for k in ('p256dh','auth')}}

def atomic(path,data):
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);tmp=path.with_name(path.name+'-'+str(uuid.uuid4())+'.tmp')
 with tmp.open('x') as f:os.chmod(str(tmp),0o600);json.dump(data,f,ensure_ascii=False)
 os.replace(str(tmp),str(path))

def payload(status,test=False):
 if test:return {'title':'iCloud 网关通知测试','body':'网页提醒已连接。这是一条测试通知，Apple 授权没有被更改。','url':'/','tag':'icloud-gateway-test'}
 if status=='OK':title='iCloud 文件网关已恢复';body='Apple 授权和目录读取检查已恢复，可以继续 Cloud 文件任务。'
 elif status in ('REAUTH_REQUIRED','APPLE_WEB_ACCESS_DISABLED'):
  title='iCloud 文件网关需要重新授权';body='请在自己的 SSH 客户端连接 ECS，运行 icloud-reconnect，并完成 Apple 验证或设备批准。'
 else:title='iCloud 文件网关检查失败';body='服务器暂时无法读取 iCloud。请查看网关状态；尚不能确定是否需要 Apple 重新授权。'
 return {'title':title,'body':body,'url':'/','tag':'icloud-gateway-health'}

class NotificationStore:
 def __init__(self,directory,helper):
  self.path=pathlib.Path(directory)/'notifications.json';self.key_path=pathlib.Path(directory)/'vapid.json';self.helper=str(helper);self.lock=threading.Lock();self.running=False
 def load(self):
  return json.loads(self.path.read_text()) if self.path.exists() else {'subscriptions':{},'health':None,'last_push':None}
 def keys(self):
  with self.lock:
   if not self.key_path.exists():
    r=subprocess.run([self.helper],input=json.dumps({'mode':'generate'}),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,universal_newlines=True,timeout=15)
    if r.returncode:raise ValueError('push runtime unavailable')
    keys=json.loads(r.stdout)
    if set(keys)!={'private_key','public_key'}:raise ValueError('unexpected push runtime response')
    atomic(self.key_path,keys)
   return json.loads(self.key_path.read_text())
 def config(self):return {'public_key':self.keys()['public_key']}
 def status(self):
  with self.lock:
   s=self.load();return {'registered_devices':sum(x.get('enabled',False) for x in s['subscriptions'].values()),'health':s['health'],'last_push':s['last_push'],'sending':self.running}
 def subscribe(self,subscription):
  s=valid_subscription(subscription);ident=hashlib.sha256(s['endpoint'].encode()).hexdigest()
  with self.lock:
   state=self.load();old=state['subscriptions'].get(ident,{})
   if not old and len(state['subscriptions'])>=32:raise ValueError('device limit reached')
   state['subscriptions'][ident]={'subscription':s,'enabled':True,'last_event':old.get('last_event'),'created_at':old.get('created_at',time.time())};atomic(self.path,state)
  return {'subscribed':True,'id':ident}
 def unsubscribe(self,ident):
  with self.lock:
   state=self.load()
   if ident in state['subscriptions']:state['subscriptions'][ident]['enabled']=False;atomic(self.path,state)
  return {'subscribed':False,'id':ident}
 def health(self,status,checked_at,mail=None):
  if status not in STATUSES:raise ValueError('invalid health state')
  if mail is not None:
   if not isinstance(mail,dict) or mail.get('status') not in ('ready','accepted','failed','auth_pending','not_configured'):raise ValueError('invalid mail state')
   mail={'status':mail['status']}
  with self.lock:
   s=self.load();old=s['health'];changed=old is None or old['status']!=status
   event=old.get('event') if old and not changed else str(uuid.uuid4())
   s['health']={'status':status,'checked_at':checked_at,'event':event,'mail':mail}
   # No routine OK message; notify only failure, or recovery following failure.
   action=status!='OK' or old is not None and old['status']!='OK'
   s['health']['notify']=action or bool(old and not changed and old.get('notify'))
   atomic(self.path,s)
  if s['health']['notify']:self.start(event,payload(status))
  return {'health_recorded':True}
 def test(self):return self.start('test-'+str(uuid.uuid4()),payload('OK',True))
 def start(self,event,message):
  with self.lock:
   if self.running:return {'queued':False,'reason':'push already in progress'}
   s=self.load();ids=[k for k,v in s['subscriptions'].items() if v.get('enabled') and v.get('last_event')!=event]
   if not ids:return {'queued':False,'reason':'no subscribed devices'}
   self.running=True
  thread=threading.Thread(target=self.send,args=(event,message,ids));thread.daemon=True;thread.start();return {'queued':True,'devices':len(ids)}
 def send(self,event,message,ids):
  accepted=0;failed=0
  try:
   keys=self.keys()
   for ident in ids:
    with self.lock:record=self.load()['subscriptions'].get(ident)
    if not record or not record.get('enabled'):continue
    request={'mode':'send','subscription':record['subscription'],'payload':message};request.update(keys)
    try:
     r=subprocess.run([self.helper],input=json.dumps(request,ensure_ascii=False),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,universal_newlines=True,timeout=20)
     result=json.loads(r.stdout);status=int(result.get('status',0));ok=r.returncode==0 and result.get('sent') is True
    except Exception:status=0;ok=False
    with self.lock:
     s=self.load();target=s['subscriptions'].get(ident)
     if target:
      target['last_http_status']=status
      if ok:target['last_event']=event
      elif status in (404,410):target['enabled']=False;target['expired_at']=time.time()
      atomic(self.path,s)
    if ok:accepted+=1
    else:failed+=1
  except Exception:failed=max(failed,len(ids)-accepted)
  finally:
   with self.lock:
    s=self.load();s['last_push']={'checked_at':datetime.datetime.utcnow().isoformat()+'Z','accepted_by_push_service':accepted,'failed':failed,'test':event.startswith('test-')};atomic(self.path,s);self.running=False
