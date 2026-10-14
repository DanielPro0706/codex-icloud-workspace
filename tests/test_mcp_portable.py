import importlib.util,pathlib,tomllib,unittest
root=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('portable_mcp',root/'scripts/portable_sync.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
class MCPTests(unittest.TestCase):
 def test_portable_remote_and_stdio_keep_environment_names_without_values(self):
  servers={'remote':{'url':'https://mcp.example.org/mcp','bearer_token_env_var':'SERVICE_TOKEN','http_headers':{'Authorization':'Bearer confidential-session'}},'stdio':{'command':'npx','args':['-y','@example/mcp'],'env':{'SERVICE_TOKEN':'confidential-session'},'env_vars':['PUBLIC_SETTING']}}
  accepted,omitted=p.portable_mcp(servers)
  self.assertEqual(accepted['remote']['bearer_token_env_var'],'SERVICE_TOKEN');self.assertNotIn('http_headers',accepted['remote'])
  self.assertEqual(accepted['stdio']['env_vars'],['PUBLIC_SETTING','SERVICE_TOKEN']);self.assertNotIn('env',accepted['stdio'])
  text='\n'.join('[mcp_servers.'+p.toml_value(k)+']\n'+'\n'.join(n+' = '+p.toml_value(v) for n,v in s.items()) for k,s in accepted.items())
  self.assertNotIn('confidential-session',text);self.assertEqual(tomllib.loads(text)['mcp_servers'],accepted)
 def test_machine_paths_auth_urls_and_argument_credentials_are_not_exported(self):
  servers={'local':{'command':'/Applications/vendor/tool'},'path':{'command':'python3','args':['/Users/owner/server.py']},'query':{'url':'https://example.org/mcp?token=private'},'loopback':{'url':'https://127.0.0.1/mcp'},'secretarg':{'command':'node','args':['server.js','--api-key','confidential-session']}}
  accepted,omitted=p.portable_mcp(servers);self.assertEqual(accepted,{});self.assertEqual(len(omitted),5)
if __name__=='__main__':unittest.main()
