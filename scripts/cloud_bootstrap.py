#!/usr/bin/env python3
"""Verify pinned content and update generated Skills with conflict checks and backups."""
import importlib.util,pathlib,json,os,time,argparse
parser=argparse.ArgumentParser();parser.add_argument('--cloud-root',type=pathlib.Path);options=parser.parse_args()
root=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('portable',root/'scripts/portable_sync.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
m=p.validate(root/'snapshot');state=root/'.portable-state.json'
current_state=json.loads(state.read_text()) if state.exists() else None
previous=current_state.get('files',{}) if current_state is not None else {}
conflicts=[];actions=[];next_state={}
for rel,digest in m['files'].items():
 parts=pathlib.Path(rel).parts
 if len(parts)<4 or parts[1]!='skills':continue
 key=str(pathlib.Path(*parts[2:]));target=root/'.agents/skills'/key
 if target.is_symlink() or not target.resolve().is_relative_to((root/'.agents/skills').resolve()):raise SystemExit('unsafe target')
 if key in next_state and next_state[key]!=digest:raise SystemExit('Duplicate Skill name conflict: '+key)
 next_state[key]=digest
 actual=p.sha(target.read_bytes()) if target.is_file() else None
 if actual==digest:continue
 if target.exists() and actual!=previous.get(key):conflicts.append(key)
 else:actions.append((target,root/'snapshot/files'/rel,rel))
if conflicts:raise SystemExit('Conflicting Skill files; no writes: '+json.dumps(conflicts))
stamp=str(time.time_ns());backup=root/'work/portable-backups'/stamp
for target,source,rel in actions:
 if target.exists():
  p.private_write(backup/target.relative_to(root),target.read_bytes())
  temp=target.with_name(target.name+'.portable-'+stamp);p.private_write(temp,source.read_bytes());os.replace(temp,target)
 else:p.private_write(target,source.read_bytes())
 target.chmod(0o700 if m.get('modes',{}).get(rel)==0o700 else 0o600)
desired_state={'files':next_state,'snapshot':m['id']}
if current_state!=desired_state:
 if state.exists():p.private_write(backup/'state.json',state.read_bytes())
 tmp=state.with_name('.portable-state.'+stamp+'.json');p.private_write(tmp,json.dumps(desired_state).encode());os.replace(tmp,state)
result={'snapshot':m['id'],'installed_files':len(actions),'gateway':'not tested by bootstrap'}
if options.cloud_root:
 from cloud_root import install
 result['cloud_root']=install(root,options.cloud_root,guidance_only=True)
print(json.dumps(result))
