#!/usr/bin/env python3
"""Owner-only interactive SSH public-key enrollment. Never accepts a private key."""
import base64,hashlib,os,pathlib,struct,sys,time,uuid
BASE=pathlib.Path('/home/icloud-gateway')

def parse_public_key(text):
 parts=text.strip().split()
 if len(parts)<2 or parts[0]!='ssh-ed25519' or len(text)>4096:raise ValueError('Paste an ssh-ed25519 PUBLIC key only')
 try:blob=base64.b64decode(parts[1],validate=True)
 except Exception:raise ValueError('Invalid public-key encoding')
 pos=0;values=[]
 for _ in range(2):
  if pos+4>len(blob):raise ValueError('Truncated public key')
  length=struct.unpack('>I',blob[pos:pos+4])[0];pos+=4
  if pos+length>len(blob):raise ValueError('Truncated public key')
  values.append(blob[pos:pos+length]);pos+=length
 if pos!=len(blob) or values[0]!=b'ssh-ed25519' or len(values[1])!=32:raise ValueError('Invalid ED25519 public key')
 fingerprint='SHA256:'+base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')
 return 'ssh-ed25519 '+parts[1],fingerprint

def main():
 if os.getuid()!=1000 or not (sys.stdin.isatty() and sys.stdout.isatty()):raise SystemExit('Use your own gateway-account SSH terminal')
 key,fingerprint=parse_public_key(input('Paste the phone ED25519 public key (never a private key): '))
 print('Phone key fingerprint:',fingerprint)
 if input('Type REGISTER to authorize this key for icloud-gateway: ')!='REGISTER':raise SystemExit('No change made')
 folder=BASE/'.ssh';path=folder/'authorized_keys'
 if folder.is_symlink() or path.is_symlink():raise SystemExit('Unsafe SSH path; no change made')
 folder.mkdir(mode=0o700,exist_ok=True);os.chmod(str(folder),0o700)
 original=path.read_bytes() if path.exists() else b''
 if key.encode() in original:print('This public key is already present; no change made');return
 backup=BASE/'.local/state/icloud-gateway/ssh-backups'/('authorized_keys-'+str(time.time())+'.txt');backup.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 with backup.open('xb') as f:os.chmod(str(backup),0o600);f.write(original)
 temp=path.with_name('authorized_keys-'+str(uuid.uuid4())+'.tmp')
 line=('no-agent-forwarding,no-port-forwarding,no-X11-forwarding '+key+' codex-phone\n').encode()
 with temp.open('xb') as f:os.chmod(str(temp),0o600);f.write(original+(b'\n' if original and not original.endswith(b'\n') else b'')+line)
 os.replace(str(temp),str(path));print('Phone public key registered. The private key stays on the phone.')
if __name__=='__main__':
 try:main()
 except ValueError as e:raise SystemExit(str(e))
