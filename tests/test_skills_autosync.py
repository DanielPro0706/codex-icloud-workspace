import importlib.util,json,pathlib,subprocess,sys,unittest,uuid,os,shutil
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import skills_autosync as auto,portable_sync as portable
SCANNER=pathlib.Path(os.environ.get('GITLEAKS_BIN') or shutil.which('gitleaks') or '/nonexistent/gitleaks')
@unittest.skipUnless(SCANNER.is_file(),'Publication tests require gitleaks on PATH or GITLEAKS_BIN')
class AutoSyncTests(unittest.TestCase):
 def git(self,path,*args):return subprocess.check_output(['git','-C',str(path)]+list(args),stderr=subprocess.DEVNULL,text=True).strip()
 def fixture(self):
  base=ROOT/'work/autosync-tests'/str(uuid.uuid4());home=base/'home';skill=home/'.agents/skills/example';skill.mkdir(parents=True)
  (skill/'SKILL.md').write_text('---\nname: example\ndescription: Synthetic fixture\n---\nVersion one.\n')
  bundle=portable.export(home,base/'exports',emit=False);remote=base/'remote.git';repo=base/'repository'
  subprocess.check_call(['git','init','--bare','-q',str(remote)])
  subprocess.check_call(['git','init','-q','-b','main',str(repo)])
  self.git(repo,'config','user.name','Fixture');self.git(repo,'config','user.email','fixture@example.invalid')
  auto.shutil.copytree(bundle,repo/'snapshot');(repo/'README.md').write_text('Initial source.\n');self.git(repo,'add','snapshot','README.md');self.git(repo,'commit','-qm','Initial fixture');self.git(repo,'remote','add','origin',str(remote));self.git(repo,'push','-qu','origin','main')
  return base,home,repo,skill
 def test_changed_skill_publishes_only_snapshot_and_retains_previous_tree(self):
  base,home,repo,skill=self.fixture();(skill/'SKILL.md').write_text('---\nname: example\ndescription: Synthetic fixture\n---\nVersion two.\n')
  result=auto.sync_once(home,repo,base/'runtime',SCANNER)
  self.assertTrue(result['changed']);self.assertTrue(pathlib.Path(result['backup'],'manifest.json').exists())
  self.assertEqual(self.git(repo,'rev-parse','HEAD'),self.git(repo,'rev-parse','origin/main'))
  self.assertTrue(all(p.startswith('snapshot/') for p in self.git(repo,'diff-tree','--no-commit-id','--name-only','-r','HEAD').splitlines()))
  self.assertFalse(auto.sync_once(home,repo,base/'runtime',SCANNER)['changed'])
 def test_dirty_source_repository_stops_without_publishing(self):
  base,home,repo,skill=self.fixture();before=self.git(repo,'rev-parse','HEAD');(repo/'snapshot/manifest.json').write_text('owner local edit')
  with self.assertRaises(ValueError):auto.sync_once(home,repo,base/'runtime',SCANNER)
  self.assertEqual(self.git(repo,'rev-parse','HEAD'),before);self.assertEqual((repo/'snapshot/manifest.json').read_text(),'owner local edit')
 def test_unexported_private_files_and_embedded_credentials_do_not_publish(self):
  base,home,repo,skill=self.fixture();before=self.git(repo,'rev-parse','HEAD')
  (home/'.codex').mkdir();(home/'.codex/auth.json').write_text('{"fixture":"not exported"}')
  (skill/'private.pem').write_text('synthetic private fixture')
  value='fixture-'+'credential-abcdefghijk'
  (skill/'helper.py').write_text('password = '+repr(value))
  with self.assertRaises(ValueError):auto.sync_once(home,repo,base/'runtime',SCANNER)
  self.assertEqual(self.git(repo,'rev-parse','HEAD'),before)
 def test_failed_push_retries_only_the_recorded_snapshot_commit(self):
  base,home,repo,skill=self.fixture();hook=base/'remote.git/hooks/pre-receive'
  hook.write_text('#!/bin/sh\nexit 1\n');hook.chmod(0o700)
  (skill/'SKILL.md').write_text('---\nname: example\ndescription: Synthetic fixture\n---\nChanged.\n')
  with self.assertRaises(ValueError):auto.sync_once(home,repo,base/'runtime',SCANNER)
  pending=json.loads((base/'runtime/pending-push.json').read_text())
  hook.rename(base/'retained-reject-hook')
  result=auto.sync_once(home,repo,base/'runtime',SCANNER)
  self.assertEqual(self.git(repo,'rev-parse','origin/main'),pending['commit'])
  self.assertFalse(result['changed']);self.assertFalse((base/'runtime/pending-push.json').exists())
 def test_missing_source_skill_never_propagates_removal(self):
  base,home,repo,skill=self.fixture();before=self.git(repo,'rev-parse','HEAD')
  skill.rename(base/'retained-owner-skill')
  with self.assertRaisesRegex(ValueError,'without propagating removals'):
   auto.sync_once(home,repo,base/'runtime',SCANNER)
  self.assertEqual(self.git(repo,'rev-parse','HEAD'),before)
  self.assertEqual(self.git(repo,'status','--porcelain'), '')
  self.assertTrue((repo/'snapshot/files/.agents/skills/example/SKILL.md').is_file())
 def test_clean_service_clone_fast_forwards_without_overwriting_edits(self):
  base,home,repo,skill=self.fixture();other=base/'maintainer'
  subprocess.check_call(['git','clone','-q','-b','main',str(base/'remote.git'),str(other)])
  self.git(other,'config','user.name','Fixture');self.git(other,'config','user.email','fixture@example.invalid')
  (other/'README.md').write_text('Reviewed source update.\n')
  self.git(other,'add','README.md');self.git(other,'commit','-qm','Reviewed source update');self.git(other,'push','-q','origin','main')
  (skill/'SKILL.md').write_text('---\nname: example\ndescription: Synthetic fixture\n---\nChanged.\n')
  result=auto.sync_once(home,repo,base/'runtime',SCANNER)
  self.assertTrue(result['changed']);self.assertEqual((repo/'README.md').read_text(),'Reviewed source update.\n')
  retained=list((base/'runtime/fast-forward-backups').glob('*/README.md'))
  self.assertEqual(len(retained),1);self.assertEqual(retained[0].read_text(),'Initial source.\n')
  self.assertTrue(all(x.startswith('snapshot/') for x in self.git(repo,'diff-tree','--no-commit-id','--name-only','-r','HEAD').splitlines()))
 def test_upstream_removal_stops_before_checkout_changes(self):
  base,home,repo,skill=self.fixture();before=self.git(repo,'rev-parse','HEAD');other=base/'maintainer'
  subprocess.check_call(['git','clone','-q','-b','main',str(base/'remote.git'),str(other)])
  self.git(other,'config','user.name','Fixture');self.git(other,'config','user.email','fixture@example.invalid')
  p=other/'snapshot/files/.agents/skills/example/SKILL.md';p.rename(base/'retained-upstream-file')
  self.git(other,'add','--all');self.git(other,'commit','-qm','Removal fixture');self.git(other,'push','-q','origin','main')
  with self.assertRaisesRegex(ValueError,'removals or renames'):auto.sync_once(home,repo,base/'runtime',SCANNER)
  self.assertEqual(self.git(repo,'rev-parse','HEAD'),before)
  self.assertTrue((repo/'snapshot/files/.agents/skills/example/SKILL.md').is_file())
 def test_pending_removal_commit_is_never_retried(self):
  base,home,repo,skill=self.fixture();parent=self.git(repo,'rev-parse','HEAD')
  (repo/'snapshot/files/.agents/skills/example/SKILL.md').rename(base/'retained-pending-file')
  self.git(repo,'add','--all','snapshot');self.git(repo,'commit','-qm','Pending removal fixture')
  runtime=base/'runtime';runtime.mkdir();auto.write_json(runtime/'pending-push.json',{'parent':parent,'commit':self.git(repo,'rev-parse','HEAD')})
  with self.assertRaisesRegex(ValueError,'removals or renames'):auto.sync_once(home,repo,runtime,SCANNER)
  self.assertEqual(self.git(repo,'rev-parse','origin/main'),parent)

if __name__=='__main__':unittest.main()
