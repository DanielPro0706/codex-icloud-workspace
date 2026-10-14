#!/usr/bin/env python3
"""Run only as icloud-gateway on ECS. Never deletes outside its own UUID file."""
import hashlib,json,pathlib,subprocess,uuid,os,sys
root=pathlib.Path('/home/icloud-gateway')
base=[str(root/'.local/bin/rclone-cn9399'),'--config',str(root/'.config/rclone/rclone-cn.conf'),'--retries','1','--low-level-retries','1','--contimeout','10s','--timeout','45s']
def run(args):
 return subprocess.run(base+args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
def checked(args,stage):
 r=run(args)
 if r.returncode:raise RuntimeError(stage+' failed, exit '+str(r.returncode)+'; raw auth output deliberately not logged')
 return r.stdout
report={'read_only':'NOT_RUN','upload':'NOT_RUN','download':'NOT_RUN','sha256_match':'NOT_RUN','trash':'NOT_RUN','absent_after_trash':'NOT_RUN'}
run_id=str(uuid.uuid4());remote='Codex:CodexGatewayTest/runs/'+run_id+'/payload.bin';report['run_id']=run_id;report['remote_file']=remote
local=root/'test-runs'/run_id;local.mkdir(parents=True,mode=0o700);report_file=local/'result.json';uploaded=False
try:
 checked(['lsf','Codex:','--max-depth','1','--dirs-only'],'read-only root listing');report['read_only']='PASS'
 source=local/'payload.bin';source.write_bytes(os.urandom(65536));source.chmod(0o600)
 checked(['copyto',str(source),remote,'--immutable'],'upload');uploaded=True;report['upload']='PASS'
 download=local/'download.bin';checked(['copyto',remote,str(download),'--immutable'],'download');report['download']='PASS'
 a=hashlib.sha256(source.read_bytes()).hexdigest();b=hashlib.sha256(download.read_bytes()).hexdigest();report['sha256']=a
 if a!=b:raise RuntimeError('SHA-256 mismatch')
 report['sha256_match']='PASS'
 # The reviewed iCloud backend implements Remove with MoveItemToTrashByID.
 checked(['deletefile',remote],'move this test file to iCloud Trash');report['trash']='PASS'
 parent=remote.rsplit('/',1)[0]
 listing=checked(['lsf',parent,'--max-depth','1'],'verify test file absence').decode()
 if 'payload.bin' in listing.splitlines():raise RuntimeError('test file still listed after Trash')
 report['absent_after_trash']='PASS'
except Exception as e:
 report['error']=str(e)
finally:
 report_file.write_text(json.dumps(report,indent=2));report_file.chmod(0o600);print(json.dumps(report,indent=2))
if 'error' in report:sys.exit(1)
