import pathlib,sys,unittest,urllib.error
root=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'.agents/skills/icloud-codex-gateway/scripts'))
from gateway import search,mkdir
from test_workspace import Fake,Response
class SearchTests(unittest.TestCase):
 def test_recursive_complete_scope_and_case_insensitive_pattern(self):
  g=Fake();g.files['Folder/sub/C.PDF']=b'pdf';g.files['Outside/ignored.pdf']=b'out'
  result=search(g,'Folder','*.pdf');self.assertTrue(result['complete']);self.assertEqual([x['path'] for x in result['matches']],['Folder/sub/C.PDF'])
  self.assertEqual(result['directories_scanned'],2)
 def test_limits_and_off_origin_stop_instead_of_returning_partial_results(self):
  g=Fake()
  with self.assertRaises(ValueError):search(g,'Folder','*',max_entries=1)
  g.listing=lambda *a,**k:[{'href':'https://outside.example/a','directory':False,'bytes':'1'}]
  with self.assertRaises(ValueError):search(g,'Folder','*')
 def test_mkdir_authorization_and_existing_targets(self):
  g=Fake()
  with self.assertRaises(ValueError):mkdir(g,'Folder/new',False)
  self.assertNotIn('Folder/new',g.dirs)
  self.assertTrue(mkdir(g,'Folder/new',True)['verified'])
  with self.assertRaises(urllib.error.HTTPError):mkdir(g,'Folder/new',True)
if __name__=='__main__':unittest.main()
