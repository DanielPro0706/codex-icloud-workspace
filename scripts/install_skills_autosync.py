#!/usr/bin/env python3
"""Preview/install the owner's narrowly scoped native Skills sync LaunchAgent."""
import argparse,hashlib,json,os,pathlib,plistlib,subprocess,sys,uuid
P=pathlib.Path
LABEL='org.example.codex.portable-skills-sync'
repo=P(__file__).resolve().parents[1]

def install(home,runtime,scanner,gh,apply=False,service_repo=None,previous_preview=None):
 from skills_autosync import verify_destination
 launch_repo=service_repo or repo
 expected='https://github.com/OWNER/PRIVATE-PORTABLE-REPO.git'
 verify_destination(launch_repo,expected,gh)
 for executable in (P(sys.executable),scanner,gh):
  if not executable.is_file() or not os.access(executable,os.X_OK):raise ValueError('Required executable is unavailable')
 runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
 config={'Label':LABEL,'ProgramArguments':[sys.executable,str(launch_repo/'scripts/skills_autosync.py'),'--home',str(home),'--repo',str(launch_repo),'--runtime',str(runtime),'--scanner',str(scanner),'--gh',str(gh),'--expected-remote',expected],
         'WorkingDirectory':str(launch_repo),'RunAtLoad':True,'StartInterval':60,
         'WatchPaths':[str(home/p) for p in ('.codex/skills','.agents/skills','.codex/AGENTS.md','.codex/config.toml')],
         'EnvironmentVariables':{'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin','GIT_TERMINAL_PROMPT':'0'},
         'StandardOutPath':str(runtime/'launchagent.stdout.log'),'StandardErrorPath':str(runtime/'launchagent.stderr.log'),
         'ProcessType':'Background'}
 data=plistlib.dumps(config);preview=runtime/(LABEL+'.plist');preview.write_bytes(data);preview.chmod(0o600)
 destination=home/'Library/LaunchAgents'/(LABEL+'.plist')
 if not apply:return {'installed':False,'preview':str(preview),'destination':str(destination)}
 if destination.is_symlink():raise ValueError('Symlinked LaunchAgent; no changes')
 if destination.exists() and destination.read_bytes()!=data:
  if not previous_preview or previous_preview.is_symlink() or destination.read_bytes()!=previous_preview.read_bytes():
   raise ValueError('Existing LaunchAgent differs; preserve and review it before replacement')
  check=subprocess.run(['launchctl','print','gui/'+str(os.getuid())+'/'+LABEL],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  if not check.returncode:raise ValueError('Stop the existing registered job before migrating its paths')
  retained=runtime/'launchagent-backups'/str(uuid.uuid4());retained.mkdir(mode=0o700,parents=True)
  old=retained/destination.name;old.write_bytes(destination.read_bytes());old.chmod(0o600)
  temp=destination.with_name(destination.name+'.update-'+str(uuid.uuid4()))
  with temp.open('xb') as f:os.chmod(temp,0o600);f.write(data)
  os.replace(temp,destination)
 destination.parent.mkdir(parents=True,exist_ok=True)
 if not destination.exists():
  with destination.open('xb') as f:os.chmod(destination,0o600);f.write(data)
 domain='gui/'+str(os.getuid());job=domain+'/'+LABEL
 check=subprocess.run(['launchctl','print',job],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 if check.returncode:
  result=subprocess.run(['launchctl','bootstrap',domain,str(destination)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
  if result.returncode:raise ValueError('LaunchAgent bootstrap failed; source and plist preserved')
 check=subprocess.run(['launchctl','print',job],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 if check.returncode:raise ValueError('LaunchAgent registration is not confirmed')
 return {'installed':True,'job':job,'plist':str(destination),'plist_sha256':hashlib.sha256(data).hexdigest(),'status_file':str(runtime/'status.json')}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--home',type=P,default=P.home());p.add_argument('--runtime',type=P,required=True);p.add_argument('--scanner',type=P,required=True);p.add_argument('--gh',type=P,required=True);p.add_argument('--service-repo',type=P);p.add_argument('--previous-preview',type=P);p.add_argument('--apply',action='store_true');a=p.parse_args()
 try:print(json.dumps(install(a.home.resolve(),a.runtime.resolve(),a.scanner.resolve(),a.gh.resolve(),a.apply,a.service_repo.resolve() if a.service_repo else None,a.previous_preview.resolve() if a.previous_preview else None)))
 except (ValueError,OSError) as e:raise SystemExit(str(e))
