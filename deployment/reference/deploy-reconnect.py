#!/usr/bin/env python3

# Historical deployment sequence: review docs before applying to your own server.
import os
if os.environ.get('REFERENCE_DEPLOY_ALLOWED') != '1':
 raise SystemExit('Read deployment/reference/README.md; explicit REFERENCE_DEPLOY_ALLOWED=1 required')
if not os.environ.get('ECS_INSTANCE_ID'):
 raise SystemExit('ECS_INSTANCE_ID must identify your own authorized server')
"""Install owner recovery code only; never initiate login or read credentials."""
import base64
import hashlib
import json
import pathlib
import subprocess
import uuid

source = pathlib.Path('./gateway-runtime/reconnect.py').read_bytes()
digest = hashlib.sha256(source).hexdigest()
code = '''import base64,hashlib,pathlib,shutil,subprocess,uuid,json
p=pathlib.Path('/usr/local/bin/icloud-reconnect')
if p.is_symlink():raise SystemExit('Unexpected helper symlink; stopped')
backup=pathlib.Path('/var/backups/icloud-gateway/reconnect-HELPER_ID')
backup.mkdir(parents=True,mode=0o700)
if p.exists():shutil.copy2(str(p),str(backup/'icloud-reconnect.previous'))
data=base64.b64decode('HELPER_PAYLOAD')
compile(data.decode(),str(p),'exec')
assert hashlib.sha256(data).hexdigest()=='HELPER_SHA'
temp=p.with_name('icloud-reconnect-'+str(uuid.uuid4())+'.new')
with temp.open('xb') as f:temp.chmod(0o755);f.write(data)
temp.replace(p)
assert hashlib.sha256(p.read_bytes()).hexdigest()=='HELPER_SHA'
r=subprocess.run(['runuser','-u','icloud-gateway','--',str(p)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
assert r.returncode==1 and 'private gateway-account SSH terminal' in r.stdout+r.stderr
print(json.dumps({'installed_sha256':'HELPER_SHA','noninteractive_refused':True,'backup':str(backup),'login_triggered':False,'services_restarted':False}))
'''.replace('HELPER_ID',str(uuid.uuid4())).replace('HELPER_PAYLOAD',base64.b64encode(source).decode()).replace('HELPER_SHA',digest)
# Shell single quoting protects the complete remote Python program.
quoted="'" + code.replace("'", "'\"'\"'") + "'"
r=subprocess.run(['/usr/local/bin/workbench','--profile',os.environ['WORKBENCH_PROFILE'],'exec','-i',os.environ['ECS_INSTANCE_ID'],'--command','python3 -c '+quoted,'--timeout','25'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
print(r.stdout+r.stderr)
if r.returncode==0:
    pathlib.Path('work/deployment-evidence/reconnect-install.txt').write_text(r.stdout+r.stderr)
raise SystemExit(r.returncode)
