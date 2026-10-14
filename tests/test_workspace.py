import importlib.util,pathlib,sys,unittest,io,urllib.error,uuid,hashlib
root=pathlib.Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'.agents/skills/icloud-codex-gateway/scripts'))
import workspace as w
class Response(io.BytesIO):
 def __init__(self,data=b'',status=200):super().__init__(data);self.status=status
class Fake:
 base='https://gateway.example.ts.net/'
 def __init__(self):self.files={'Folder/a.txt':b'original','Folder/sub/b.txt':b'unchanged'};self.dirs={'Folder','Folder/sub'};self.writes=[];self.trash=[]
 def listing(self,path='',depth='1'):
  path=path.strip('/');items=[{'href':'/'+path+'/','directory':True,'bytes':None}]
  if depth=='0':return items
  for p in sorted(self.dirs|set(self.files)):
   if p==path or not p.startswith(path+'/'):continue
   rel=p[len(path)+1:]
   if '/' in rel:continue
   items.append({'href':'/'+p+('/' if p in self.dirs else ''),'directory':p in self.dirs,'bytes':str(len(self.files[p])) if p in self.files else None})
  return items
 def req(self,method,path='',data=None,headers=None):
  path=path.strip('/')
  if method=='GET':
   if path not in self.files:raise urllib.error.HTTPError(path,404,'missing',None,None)
   return Response(self.files[path])
  if method=='HEAD':
   if path not in self.files:raise urllib.error.HTTPError(path,404,'missing',None,None)
   return Response()
  if method=='MKCOL':
   if path in self.dirs:raise urllib.error.HTTPError(path,405,'exists',None,None)
   self.dirs.add(path);return Response(status=201)
  if method=='PUT':self.files[path]=data;self.writes.append(path);return Response(status=201)
  if method=='DELETE':self.trash.append((path,self.files.pop(path)));return Response(status=204)
  raise AssertionError(method)
class WorkspaceTests(unittest.TestCase):
 def fresh(self):
  p=root/'work/workspace-tests'/str(uuid.uuid4());g=Fake();w.open_workspace(g,'Folder',p,100,10000);return p,g
 def test_checkout_reuse_and_conflict_stops_all_writes(self):
  p,g=self.fresh();self.assertEqual((p/'files/a.txt').read_bytes(),b'original')
  (p/'files/a.txt').write_bytes(b'local change');(p/'files/new.txt').write_bytes(b'new')
  self.assertTrue(w.open_workspace(g,'Folder',p,100,10000)['reused']);self.assertEqual((p/'files/a.txt').read_bytes(),b'local change')
  plan=w.plan(p);g.files['Folder/a.txt']=b'changed remotely'
  with self.assertRaises(ValueError):w.push(g,p,True,plan['plan_sha256'])
  self.assertEqual(g.writes,[]);self.assertEqual(g.files['Folder/a.txt'],b'changed remotely')
 def test_authorized_scoped_update_and_digest_verification(self):
  p,g=self.fresh();(p/'files/a.txt').write_bytes(b'updated');(p/'files/new').mkdir();(p/'files/new/c.txt').write_bytes(b'new file');plan=w.plan(p)
  with self.assertRaises(ValueError):w.push(g,p,False,plan['plan_sha256'])
  self.assertEqual(g.writes,[])
  result=w.push(g,p,True,plan['plan_sha256']);self.assertEqual(len(result['applied']),2);self.assertEqual(w.plan(p)['changes'],[])
  self.assertEqual(g.files['Folder/a.txt'],b'updated');self.assertEqual(g.files['Folder/sub/b.txt'],b'unchanged')
 def test_plan_change_and_trash_require_explicit_permission(self):
  p,g=self.fresh();(p/'files/a.txt').write_bytes(b'changed');plan=w.plan(p);(p/'files/a.txt').write_bytes(b'again')
  with self.assertRaises(ValueError):w.push(g,p,True,plan['plan_sha256'])
  # Move local file aside rather than delete it.
  (p/'files/a.txt').rename(p/'local-file-kept.txt');plan=w.plan(p)
  with self.assertRaises(ValueError):w.push(g,p,True,plan['plan_sha256'])
  self.assertEqual(g.trash,[])
  w.push(g,p,True,plan['plan_sha256'],allow_trash=True);self.assertEqual([x[0] for x in g.trash],['Folder/a.txt']);self.assertIn('Folder/sub/b.txt',g.files)
 def test_listing_scope_and_limits(self):
  p=root/'work/workspace-tests'/str(uuid.uuid4());g=Fake()
  with self.assertRaises(ValueError):w.open_workspace(g,'Folder',p,1,2)
  self.assertFalse(p.exists())
  with self.assertRaises(ValueError):w.href_path(g,'https://evil.example/Folder/a')
class SelectionTests(unittest.TestCase):
 def test_new_chat_follows_selection_old_chat_preserves_edits(self):
  g=Fake();g.chosen={'selected':True,'folder':'Folder','revision':'one'}
  old=g.req
  def request(method,path='',data=None,headers=None):
   if path=='__codex_gateway_v1__/selection':return Response(w.json.dumps(g.chosen).encode())
   return old(method,path,data,headers)
  g.req=request
  base=root/'work/selection-tests'/str(uuid.uuid4())
  first=w.activate(g,base/'chat-a',checkout=True);w.P(first['workspace'],'a.txt').write_text('unsaved')
  g.dirs.add('Other');g.chosen={'selected':True,'folder':'Other','revision':'two'}
  self.assertEqual(w.activate(g,base/'chat-a')['remote_folder'],'Folder')
  self.assertEqual(w.P(first['workspace'],'a.txt').read_text(),'unsaved')
  self.assertEqual(w.activate(g,base/'chat-b')['remote_folder'],'Other')
 def test_empty_selection_does_not_create_binding(self):
  g=Fake();g.req=lambda *a,**k:Response(b'{"selected":false}')
  base=root/'work/selection-tests'/str(uuid.uuid4())
  self.assertFalse(w.activate(g,base)['selected']);self.assertFalse(base.exists())
if __name__=='__main__':unittest.main()
