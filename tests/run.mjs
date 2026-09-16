import {build} from 'rolldown';
import {resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
const root=process.cwd();
const fixtures=spawnSync('python3',['tests/make-parity-fixtures.py'],{stdio:'inherit'});
if(fixtures.status!==0)process.exit(fixtures.status||1);
for(const entry of ['tests/agent-flow.ts','lib/tools.ts']){
  await build({input:resolve(entry),platform:'node',external:[/^node:/],plugins:[{
    name:'test-runtime',
    resolveId(id){
      if(id==='cloudflare:workers')return resolve(root,'tests/mock-runtime.ts');
      if(id.startsWith('@/'))return resolve(root,id.slice(2))+'.ts';
    }
  }],output:{file:resolve('.sites-runtime',entry.includes('agent-flow')?'agent-flow.mjs':'tools.mjs'),format:'esm'}});
}
for(const path of ['.sites-runtime/agent-flow.mjs','tests/parity.mjs']){
  const r=spawnSync(process.execPath,[path],{stdio:'inherit'});if(r.status!==0)process.exit(r.status||1);
}
