import pathlib,unittest,uuid
from test_workspace import Fake,Response,root,w

class DemandFake(Fake):
 def __init__(self):
  super().__init__();self.gets=[]
 def listing(self,path='',depth='1'):
  path=path.strip('/')
  if path in self.files:return [{'href':'/'+path,'directory':False,'bytes':str(len(self.files[path]))}]
  if path not in self.dirs:raise ValueError('missing directory')
  return super().listing(path,depth)
 def req(self,method,path='',data=None,headers=None):
  if path=='__codex_gateway_v1__/selection':return Response(b'{"selected":true,"folder":"Folder","revision":"one"}')
  if method=='GET':self.gets.append(path.strip('/'))
  return super().req(method,path,data,headers)

class DemandTests(unittest.TestCase):
 def fresh(self):
  return root/'work/demand-tests'/str(uuid.uuid4()),DemandFake()
 def test_large_or_credential_neighbours_do_not_block_binding(self):
  base,g=self.fresh();g.files['Folder/SelfIntro.key']=b'not requested';g.files['Folder/.env']=b'synthetic';g.files['Folder/large.mov']=b'not requested'
  old=g.listing
  def listing(path='',depth='1'):
   rows=old(path,depth)
   for row in rows:
    if row['href'].endswith('large.mov'):row['bytes']=str(2*1024**3)
   return rows
  g.listing=listing;r=w.activate(g,base)
  self.assertEqual(r['mode'],'on-demand-and-writeback');self.assertEqual(g.gets,[])
  self.assertIn('SelfIntro.key',[e['path'] for e in r['entries']]);self.assertTrue(r['complete'])
  self.assertEqual(list(pathlib.Path(r['workspace']).iterdir()),[])
 def test_only_requested_files_download_and_unfetched_files_are_never_trash(self):
  base,g=self.fresh();r=w.activate(g,base);controller=pathlib.Path(r['controller'])
  w.fetch(g,controller,['a.txt'],100,10000)
  self.assertEqual(g.gets,['Folder/a.txt']);self.assertEqual((controller/'files/a.txt').read_bytes(),b'original')
  (controller/'files/a.txt').write_bytes(b'edited');self.assertEqual(w.plan(controller)['changes'][0]['path'],'a.txt')
  self.assertFalse(any(c['path']=='sub/b.txt' for c in w.plan(controller)['changes']))
  w.fetch(g,controller,['a.txt'],100,10000);self.assertEqual(g.gets,['Folder/a.txt']);self.assertEqual((controller/'files/a.txt').read_bytes(),b'edited')
  g.files['Folder/a.txt']=b'remote change'
  with self.assertRaises(ValueError):w.push(g,controller,True,w.plan(controller)['plan_sha256'])
  self.assertEqual(g.writes,[])
 def test_requested_subtree_and_unsafe_targets(self):
  base,g=self.fresh();r=w.activate(g,base);controller=pathlib.Path(r['controller'])
  w.fetch(g,controller,['sub'],100,10000);self.assertEqual(g.gets,['Folder/sub/b.txt'])
  g.files['Folder/.env']=b'synthetic secret fixture'
  for path in ['../outside','.env','/absolute']:
   with self.assertRaises(ValueError):w.fetch(g,controller,[path],100,10000)
  (controller/'files/escape').symlink_to(controller/'staging',target_is_directory=True)
  g.dirs.add('Folder/escape');g.files['Folder/escape/file']=b'synthetic'
  with self.assertRaises(ValueError):w.fetch(g,controller,['escape/file'],100,10000)
 def test_partial_download_is_not_a_local_file_or_a_writeback_plan(self):
  base,g=self.fresh();r=w.activate(g,base);controller=pathlib.Path(r['controller'])
  old=g.req
  class Broken(Response):
   def read(self,*a):raise OSError('synthetic interrupted download')
  g.req=lambda method,path='',**kw:Broken() if method=='GET' else old(method,path,**kw)
  with self.assertRaises(OSError):w.fetch(g,controller,['a.txt'],100,10000)
  self.assertFalse((controller/'files/a.txt').exists());self.assertEqual(w.plan(controller)['changes'],[])

if __name__=='__main__':unittest.main()
