"""Send fixed gateway notices only after the deploying owner explicitly opts in."""
import datetime,json,os,pathlib,re,subprocess,time,uuid
RECIPIENT=os.environ.get('ICLOUD_ALERT_EMAIL','')
ENABLED=os.environ.get('ICLOUD_ALERT_EMAIL_ENABLED')=='1'
CLI='/home/icloud-gateway/.local/bin/agently-cli'
STATE=pathlib.Path('/home/icloud-gateway/.local/state/icloud-gateway/mail-notifications.json')
MESSAGES={
 'REAUTH_REQUIRED':('iCloud 文件网关需要重新授权','iCloud 文件网关无法继续使用当前 Apple 授权。请在自己的手机 SSH 客户端连接 icloud-gateway@gateway.example.ts.net，运行 icloud-reconnect，完成 Apple 验证或设备批准。\n私有工作区：https://gateway.example.ts.net/\n请不要把 Apple 密码或验证码发到聊天。'),
 'APPLE_WEB_ACCESS_DISABLED':('iCloud 文件网关需要重新授权','Apple 网页数据访问未获批准。请检查账户的网页数据访问设置，在自己的 SSH 终端运行 icloud-reconnect，并完成受信任设备提示。\n私有工作区：https://gateway.example.ts.net/'),
 'OK':('iCloud 文件网关已恢复','服务器已重新通过 Apple 授权和目录读取检查，可以继续 Cloud 文件任务。\n私有工作区：https://gateway.example.ts.net/'),
 'CHECK_FAILED':('iCloud 文件网关检查失败','服务器暂时无法读取 iCloud，尚不能确定是否需要重新授权。请在自己的 SSH 终端运行 icloud-status 查看状态。\n私有工作区：https://gateway.example.ts.net/'),
 'NETWORK_TIMEOUT':('iCloud 文件网关连接超时','服务器读取 iCloud 的检查超时，尚不能确定是否需要重新授权。请稍后检查 icloud-status。'),
 'REGION_INCOMPATIBLE':('iCloud 文件网关地区配置需要检查','服务器遇到 iCloud 地区兼容错误，请检查大陆候选版配置。请不要直接用官方版本覆盖候选版。'),
 'TEST':('iCloud 网关邮件提醒测试','这是一条服务器发送的邮件提醒测试，Apple 授权没有被更改。请确认手机收到了这封邮件。\n私有工作区：https://gateway.example.ts.net/')}

def parsed(text):
 for match in re.finditer(r'\{',text):
  try:return json.JSONDecoder().raw_decode(text[match.start():])[0]
  except ValueError:pass
 return None

def run(args):
 r=subprocess.run([CLI]+args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=40)
 return r.returncode,parsed(r.stdout)

def token_in(value):
 if isinstance(value,str) and re.fullmatch(r'ctk_[A-Za-z0-9_-]+',value):return value
 if isinstance(value,dict):values=value.values()
 elif isinstance(value,list):values=value
 else:return None
 matches=[token_in(v) for v in values];matches=[x for x in matches if x]
 return matches[0] if len(matches)==1 else None

def send(kind):
 if kind not in MESSAGES:raise ValueError('Unsupported notice')
 if not ENABLED or not RECIPIENT or RECIPIENT.endswith('.invalid'):return False,'not_configured'
 subject,body=MESSAGES[kind];args=['message','+send','--to',RECIPIENT,'--subject',subject,'--body',body]
 code,data=run(args)
 token=token_in(data)
 if code==8 and not token:return False,'failed'
 if code in (0,8) and token:
  # Deployment opt-in authorizes only these fixed notices to this recipient.
  code,data=run(args+['--confirmation-token',token])
 complete=code==0 and isinstance(data,dict) and data.get('ok') is True and token_in(data) is None
 return complete,'accepted' if complete else 'auth_pending' if code==3 else 'failed'

def save(data):
 STATE.parent.mkdir(parents=True,exist_ok=True,mode=0o700);temp=STATE.with_name('mail-notifications-'+str(uuid.uuid4())+'.tmp')
 with temp.open('x') as f:os.chmod(str(temp),0o600);json.dump(data,f)
 os.replace(str(temp),str(STATE))

def notify(status,test=False):
 if not ENABLED or not RECIPIENT or RECIPIENT.endswith('.invalid'):return {'status':'not_configured'}
 if test:
  success,result=send('TEST');return {'status':result,'test':True}
 old=json.loads(STATE.read_text()) if STATE.exists() else {};changed=old.get('health_status')!=status
 event=str(uuid.uuid4()) if changed else old.get('event')
 action=status!='OK' or bool(old.get('notify')) and not changed or old.get('health_status') not in (None,'OK')
 if not action:
  code,data=run(['+me']);result='ready' if code==0 and data and data.get('ok') else 'auth_pending'
 elif old.get('accepted_event')==event:result='accepted'
 else:
  success,result=send(status)
  if success:old['accepted_event']=event
 old.update({'health_status':status,'event':event,'notify':action,'status':result,'checked_at':datetime.datetime.utcnow().isoformat()+'Z'});save(old)
 return {'status':result}
