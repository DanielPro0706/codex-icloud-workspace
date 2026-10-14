"""Fast-forward a clean trusted checkout with file preservation before mutation."""
import json,pathlib,subprocess,uuid
P=pathlib.Path

def fast_forward(repo,backups,git):
 head=git(repo,'rev-parse','HEAD');remote=git(repo,'rev-parse','origin/main')
 if head==remote:return None
 if git(repo,'status','--porcelain','--untracked-files=no'):raise ValueError('Tracked edits prevent repository refresh')
 ancestor=subprocess.run(['git','-C',str(repo),'merge-base','--is-ancestor',head,remote],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 if ancestor.returncode:raise ValueError('Repository diverged; no merge or overwrite')
 if git(repo,'diff','--name-status','--diff-filter=DR','--find-renames',head,remote):
  raise ValueError('Upstream removals or renames require review; checkout preserved')
 paths=[p for p in git(repo,'diff','--name-only','-z',head,remote).split('\0') if p]
 retained=backups/str(uuid.uuid4());retained.mkdir(parents=True,mode=0o700)
 for name in paths:
  source=repo/name
  if source.is_symlink() or not source.resolve().is_relative_to(repo.resolve()):raise ValueError('Unsafe refresh source path')
  if source.exists():
   if not source.is_file():raise ValueError('Unexpected refresh source type')
   target=retained/name;target.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
   with target.open('xb') as f:target.chmod(0o600);f.write(source.read_bytes())
 (retained/'refresh.json').write_text(json.dumps({'before':head,'after':remote,'paths':paths}));(retained/'refresh.json').chmod(0o600)
 git(repo,'merge','--ff-only','origin/main')
 return str(retained)
