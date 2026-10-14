import importlib.util,pathlib,subprocess,json,sys,uuid
root=pathlib.Path(__file__).resolve().parents[1];base=root/'work'/('portable-test-'+uuid.uuid4().hex);src=base/'source';dst=base/'target';out=base/'snapshots';src.mkdir(parents=True);dst.mkdir()
script=root/'scripts/portable_sync.py'
def run(*args,code=0):
 r=subprocess.run([sys.executable,str(script),*map(str,args)],capture_output=True,text=True)
 assert r.returncode==code,(r.returncode,r.stdout,r.stderr);return r
skill=src/'.agents/skills/example';skill.mkdir(parents=True)
(skill/'SKILL.md').write_text('---\nname: example\ndescription: test\n---\nTest\n');(skill/'.env').write_text('secret=NOT_FOR_EXPORT');(skill/'cache').mkdir();(skill/'cache/a.json').write_text('{}')
(src/'.codex').mkdir();(src/'.codex/auth.json').write_text('{"secret":"not exported"}');(src/'.codex/state.sqlite').write_text('private');(src/'.codex/config.toml').write_text('model="test"\napi_key="not exported"\n[mcp_servers.local]\ncommand="mac-only"\n')
run('export','--home',src,'--out',out);bundle=next(out.iterdir());manifest=json.loads((bundle/'manifest.json').read_text())
assert len(manifest['files'])==2
run('import','--home',dst,'--bundle',bundle);assert not (dst/'.agents').exists()
run('import','--home',dst,'--bundle',bundle,'--apply');run('import','--home',dst,'--bundle',bundle,'--apply')
assert not (dst/'.codex/config.toml').exists()
f=dst/'.agents/skills/example/SKILL.md';f.write_text('local edit')
run('import','--home',dst,'--bundle',bundle,'--apply',code=2);assert f.read_text()=='local edit'
f.write_text((bundle/'files/.agents/skills/example/SKILL.md').read_text());(skill/'SKILL.md').write_text('upstream new')
run('export','--home',src,'--out',out);new=next(x for x in out.iterdir() if x!=bundle)
run('import','--home',dst,'--bundle',new,'--apply');assert f.read_text()=='upstream new';assert list((dst/'.codex/portable-backups').glob('*/.agents/skills/example/SKILL.md'))
(bundle/'files/.agents/skills/example/SKILL.md').write_text('tampered');r=run('verify','--bundle',bundle,code=1)
print('PASS: credential/runtime exclusions, dry run, idempotent import, conflict refusal, backup, tamper rejection')
