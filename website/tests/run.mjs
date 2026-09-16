import {build} from 'rolldown';
import {resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
await build({input:resolve('tests/proxy.ts'),platform:'node',external:[/^node:/],plugins:[{
  name:'test-runtime',resolveId(id){
    if(id==='cloudflare:workers')return resolve('tests/mock-runtime.ts');
    if(id.startsWith('@/'))return resolve(id.slice(2))+'.ts';
  }
}],output:{file:resolve('.sites-runtime/proxy-tests.mjs'),format:'esm'}});
const r=spawnSync(process.execPath,['.sites-runtime/proxy-tests.mjs'],{stdio:'inherit'});
process.exit(r.status??1);
