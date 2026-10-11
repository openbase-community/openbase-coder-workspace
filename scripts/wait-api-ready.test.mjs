import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { waitForApi, apiHealthUrl } from './wait-api-ready.mjs';
async function server(t, handler) {
  const s = createServer(handler); await new Promise(r => s.listen(0, '127.0.0.1', r));
  t.after(() => new Promise(r => s.close(r)));
  return `http://127.0.0.1:${s.address().port}/api/health/`;
}
test('waits through failed startup before accepting actual API JSON', async t => {
  let calls=0; const url=await server(t,(req,res)=>{res.writeHead(++calls<3?503:200,{'content-type':'application/json'});res.end(JSON.stringify({status:calls<3?'starting':'ok'}));});
  await waitForApi({url,timeoutMs:1000,intervalMs:10});assert.equal(calls,3);
});
test('HTML dashboard with status 200 is not an API readiness pass', async t => {
  const url=await server(t,(req,res)=>res.end('<html>dashboard</html>'));
  await assert.rejects(waitForApi({url,timeoutMs:80,intervalMs:10}),/did not become ready/);
});
test('unresponsive API is bounded',async t=>{
  const url=await server(t,()=>{}); const started=Date.now();
  await assert.rejects(waitForApi({url,timeoutMs:80,intervalMs:5}),/did not become ready/);
  assert.ok(Date.now()-started<1000);
});
test('uses configured binding and maps wildcard to loopback',()=>{
  assert.equal(apiHealthUrl({HOME:'/nonexistent',OPENBASE_CODER_CLI_HOST:'0.0.0.0',OPENBASE_CODER_CLI_PORT:'8999'}),'http://127.0.0.1:8999/api/health/');
});
