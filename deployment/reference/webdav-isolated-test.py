#!/usr/bin/env python3
import pathlib,urllib.request,urllib.error,base64,json,uuid,os,hashlib
root=pathlib.Path('/home/icloud-gateway')
e=dict(x.split('=',1) for x in (root/'.config/icloud-gateway/webdav.env').read_text().splitlines())
auth='Basic '+base64.b64encode((e['RCLONE_USER']+':'+e['RCLONE_PASS']).encode()).decode()
url='http://127.0.0.1:18765/'
def req(method,path='',data=None,extra=None):
 h={'Authorization':auth};h.update(extra or {})
 return urllib.request.urlopen(urllib.request.Request(url+path,data=data,headers=h,method=method),timeout=90)
report={};run_id=str(uuid.uuid4());parent='CodexGatewayTest/runs/'+run_id;target=parent+'/webdav-payload.bin';b=os.urandom(32768)
report['run_id']=run_id;report['remote_file']=target
with req('PROPFIND','',extra={'Depth':'0'}) as r:report['read_only_http']=r.status
with req('MKCOL',parent) as r:report['mkdir_http']=r.status
with req('PUT',target,b,{'If-None-Match':'*'}) as r:report['upload_http']=r.status
with req('GET',target) as r:download=r.read();report['download_http']=r.status
assert hashlib.sha256(b).digest()==hashlib.sha256(download).digest(),'SHA256 mismatch'
report['sha256_match']=True;report['sha256']=hashlib.sha256(b).hexdigest()
with req('DELETE',target) as r:report['trash_http']=r.status
try:
 with req('GET',target) as r:raise RuntimeError('Test file still readable after delete')
except urllib.error.HTTPError as x:
 assert x.code==404;report['after_trash_http']=404
print(json.dumps(report,indent=2))
