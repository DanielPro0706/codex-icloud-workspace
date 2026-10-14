import importlib.util,json,pathlib,unittest,uuid
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('cloud_root',ROOT/'scripts/cloud_root.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class CloudRootTests(unittest.TestCase):
 def fixture(self):
  base=ROOT/'work/cloud-root-tests'/str(uuid.uuid4());repo=base/'codex-portable';skill=repo/'.agents/skills/icloud-codex-gateway';skill.mkdir(parents=True)
  (skill/'SKILL.md').write_text('---\nname: icloud-codex-gateway\ndescription: Use the selected cloud folder for file tasks.\n---\nsynthetic trusted skill\n')
  (base/'AGENTS.md').write_text('Keep the owner instructions.\n');return base,repo
 def test_parent_discovery_idempotence_and_owner_text_preserved(self):
  base,repo=self.fixture();m.install(repo,base)
  entry=base/'.agents/skills/icloud-codex-gateway/SKILL.md'
  self.assertEqual(entry.read_bytes(),(repo/'.agents/skills/icloud-codex-gateway/SKILL.md').read_bytes())
  guidance=(base/'AGENTS.md').read_text();self.assertIn('Keep the owner instructions.',guidance);self.assertIn('workspace.py activate',guidance)
  self.assertEqual(m.install(repo,base)['changed'],False);self.assertEqual((base/'AGENTS.md').read_text(),guidance)
 def test_unmanaged_skill_conflict_stops_all_mutation(self):
  base,repo=self.fixture();target=base/'.agents/skills/icloud-codex-gateway';target.mkdir(parents=True);(target/'SKILL.md').write_text('owner local edit')
  before=(base/'AGENTS.md').read_bytes()
  with self.assertRaises(ValueError):m.install(repo,base)
  self.assertEqual((base/'AGENTS.md').read_bytes(),before);self.assertFalse((base/'.codex-portable-root.json').exists())
 def test_owner_edit_to_managed_guidance_is_a_conflict(self):
  base,repo=self.fixture();m.install(repo,base);p=base/'AGENTS.md';p.write_text(p.read_text().replace('workspace.py activate','owner custom command'))
  before=p.read_bytes()
  with self.assertRaises(ValueError):m.install(repo,base)
  self.assertEqual(p.read_bytes(),before)

 def test_readonly_skill_mount_uses_owned_guidance_index(self):
  base,repo=self.fixture();(base/'.agents').mkdir()
  with patch.object(m,'skill_links_available',return_value=False):
   result=m.install(repo,base)
   self.assertEqual(result['skill_discovery'],'guidance-index')
   self.assertFalse((base/'.agents/skills').exists())
   index=json.loads((base/'.codex-portable-skills.json').read_text())
   self.assertEqual(index['skills'][0]['name'],'icloud-codex-gateway')
   self.assertIn('selected cloud folder',index['skills'][0]['description'])
   self.assertEqual(index['skills'][0]['path'],str(repo/'.agents/skills/icloud-codex-gateway/SKILL.md'))
   self.assertIn('.codex-portable-skills.json',(base/'AGENTS.md').read_text())
   self.assertIn('Keep the owner instructions.',(base/'AGENTS.md').read_text())
   self.assertFalse(m.install(repo,base)['changed'])

 def test_explicit_cloud_guidance_preserves_even_writable_platform_folder(self):
  base,repo=self.fixture();platform=base/'.agents';platform.mkdir()
  (platform/'owner.txt').write_text('platform-owned content')
  result=m.install(repo,base,guidance_only=True)
  self.assertEqual(result['skill_discovery'],'guidance-index')
  self.assertFalse((platform/'skills').exists())
  self.assertEqual((platform/'owner.txt').read_text(),'platform-owned content')

 def test_guidance_index_edit_stops_before_mutating_root(self):
  base,repo=self.fixture()
  with patch.object(m,'skill_links_available',return_value=False):
   m.install(repo,base);index=base/'.codex-portable-skills.json'
   index.write_text('owner replacement')
   before=(base/'AGENTS.md').read_bytes();record=(base/'.codex-portable-root.json').read_bytes()
   with self.assertRaises(ValueError):m.install(repo,base)
   self.assertEqual((base/'AGENTS.md').read_bytes(),before)
   self.assertEqual((base/'.codex-portable-root.json').read_bytes(),record)
   self.assertEqual(index.read_text(),'owner replacement')

 def test_index_refresh_preserves_previous_index_and_adds_skill(self):
  base,repo=self.fixture()
  with patch.object(m,'skill_links_available',return_value=False):
   m.install(repo,base);old=(base/'.codex-portable-skills.json').read_bytes()
   skill=repo/'.agents/skills/new-skill';skill.mkdir()
   (skill/'SKILL.md').write_text('---\nname: new-skill\ndescription: |\n  A new reusable workflow.\n  Read this for its task.\n---\n')
   result=m.install(repo,base)
   self.assertEqual((pathlib.Path(result['backup'])/'skills-index.json').read_bytes(),old)
   skills=json.loads((base/'.codex-portable-skills.json').read_text())['skills']
   self.assertEqual(len(skills),2);self.assertEqual(skills[1]['description'],'A new reusable workflow. Read this for its task.')

 def test_index_rejects_missing_metadata_without_partial_guidance(self):
  base,repo=self.fixture();p=repo/'.agents/skills/icloud-codex-gateway/SKILL.md'
  p.write_text('---\nname: icloud-codex-gateway\n---\nmissing description')
  before=(base/'AGENTS.md').read_bytes()
  with patch.object(m,'skill_links_available',return_value=False):
   with self.assertRaises(ValueError):m.install(repo,base)
  self.assertEqual((base/'AGENTS.md').read_bytes(),before)
  self.assertFalse((base/'.codex-portable-root.json').exists())

if __name__=='__main__':unittest.main()
