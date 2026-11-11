import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { once } from 'node:events';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

function runtime(t) {
  const dir = mkdtempSync(join(tmpdir(),'pi-protocol-'));
  const child = spawn(process.execPath, ['src/server.mjs'], { cwd: new URL('..', import.meta.url), env: { PATH: process.env.PATH, COMIC_AGENT_DATA: dir, PI_OFFLINE: '1' } });
  t.after(() => {child.kill();rmSync(dir,{recursive:true,force:true});});
  const lines = createInterface({ input: child.stdout });
  const queue = [], waiters = [];
  lines.on('line', line => { const value = JSON.parse(line); const waiter = waiters.shift(); waiter ? waiter(value) : queue.push(value); });
  child.on('exit', code => { for (const waiter of waiters.splice(0)) waiter({ type: 'exit', code }); });
  return { child, send: value => child.stdin.write(JSON.stringify(value) + '\n'), next: () => queue.length ? Promise.resolve(queue.shift()) : new Promise(resolve => waiters.push(resolve)) };
}

test('health works without provider credentials and rejects incompatible clients', { timeout: 15000 }, async t => {
  const r = runtime(t);
  r.send({ v: 1, type: 'health', request_id: 'h' });
  const health = await r.next();
  assert.equal(health.type, 'result');
  assert.equal(health.request_id, 'h');
  assert.equal(health.data.sdk, '1.5.0');
  r.send({ v: 99, type: 'health', request_id: 'bad' });
  assert.equal((await r.next()).error.code, 'protocol_mismatch');
  const exited = once(r.child, 'exit');
  r.send({ v: 1, type: 'shutdown', request_id: 's' });
  assert.equal((await r.next()).request_id, 's');
  assert.equal((await exited)[0], 0);
});

test('unconfigured runs fail explicitly without exposing credentials', { timeout: 15000 }, async t => {
  const r = runtime(t);
  r.send({ v: 1, type: 'run', request_id: 'q', run_id: 'r', session_id: 's', project_id: 'p', secret: 'NEVER-ECHO-THIS', prompt: 'hello' });
  const reply = await r.next();
  assert.equal(reply.error.code, 'configuration_missing');
  assert.equal(reply.run_id, 'r');
  assert.equal(JSON.stringify(reply).includes('NEVER-ECHO-THIS'), false);
});

test('real Pi SDK streams a provider response without enabling coding tools', { timeout: 20000 }, async t => {
  const { createServer } = await import('node:http');
  const { mkdtemp, rm, readFile, readdir } = await import('node:fs/promises');
  const { tmpdir } = await import('node:os');
  const { join } = await import('node:path');
  const dir = await mkdtemp(join(tmpdir(), 'comic-pi-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  let submitted;
  const requests = [];
  const server = createServer(async (req, res) => {
    let body = ''; for await (const chunk of req) body += chunk;
    submitted = JSON.parse(body); requests.push(submitted);
    res.writeHead(200, { 'Content-Type': 'text/event-stream' });
    for (const chunk of [
      { id: 'fixture', object: 'chat.completion.chunk', created: 1, model: 'fixture', choices: [{ index: 0, delta: { role: 'assistant', content: '依据第一章' }, finish_reason: null }] },
      { id: 'fixture', object: 'chat.completion.chunk', created: 1, model: 'fixture', choices: [{ index: 0, delta: {}, finish_reason: 'stop' }], ...(requests.length===1?{usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 }}:{}) },
    ]) res.write(`data: ${JSON.stringify(chunk)}\n\n`);
    res.end('data: [DONE]\n\n');
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  t.after(() => server.close());
  const child = spawn(process.execPath, ['src/server.mjs'], { cwd: new URL('..', import.meta.url), env: { PATH: process.env.PATH, COMIC_AGENT_DATA: dir, PI_OFFLINE: '1' } });
  t.after(() => child.kill());
  const lines = createInterface({ input: child.stdout });
  const replies = [], waiting = [];
  lines.on('line', line => { const m = JSON.parse(line); if(m.type !== 'event') { const waiter = waiting.shift(); waiter ? waiter(m) : replies.push(m); } });
  const reply = () => replies.length ? Promise.resolve(replies.shift()) : new Promise(resolve => waiting.push(resolve));
  child.stdin.write(JSON.stringify({ v: 1, type: 'run', request_id: 'q', run_id: 'r', project_id: 'p', session_id: 's', prompt: '主角是谁', secret: 'private-fixture-key', config: { model: 'fixture', url: `http://127.0.0.1:${server.address().port}/v1` } }) + '\n');
  let result;
  result = await reply();
  assert.equal(result?.type, 'result', JSON.stringify(result));
  assert.equal(result.data.text, '依据第一章');
  assert.equal(result.data.usage.totalTokens,15);
  child.stdin.write(JSON.stringify({ v: 1, type: 'run', request_id: 'q2', run_id: 'r2', project_id: 'p', session_id: 's', prompt: '接着解释', secret: 'private-fixture-key', config: { model: 'fixture', url: `http://127.0.0.1:${server.address().port}/v1` } }) + '\n');
  // A new iterator is needed after the first reply; preserve the stream between replies.
  result = await reply();
  assert.equal(result?.type, 'result');
  assert.equal(result.data.usage,null);
  assert.equal(requests[1].messages.some(m => m.role === 'user' && JSON.stringify(m.content).includes('主角是谁')), true);
  assert.equal(submitted.tools?.length || 0, 0);
  assert.equal(JSON.stringify(submitted).includes('private-fixture-key'), false);
  child.stdin.write(JSON.stringify({ v:1,type:'run',request_id:'q3',run_id:'r3',project_id:'p',session_id:'production',prompt:'生产',secret:'private-fixture-key',config:{model:'fixture',url:`http://127.0.0.1:${server.address().port}/v1`},tools:['project_query'],final_only:true})+'\n');
  assert.equal((await reply()).type,'result');
  assert.deepEqual(submitted.tools.map(t=>t.function.name),['project_query']);
  for(const [id,tools,names] of [['legacy',true,['project_query','propose_changes']],['image-plan',['project_query','propose_changes','propose_image'],['project_query','propose_image','propose_changes']]]){
    child.stdin.write(JSON.stringify({v:1,type:'run',request_id:id,run_id:id,project_id:'p',session_id:id,prompt:'工具权限边界',secret:'private-fixture-key',config:{model:'fixture',url:`http://127.0.0.1:${server.address().port}/v1`},tools})+'\n');
    assert.equal((await reply()).type,'result');
    assert.deepEqual(submitted.tools.map(t=>t.function.name).sort(),[...names].sort());
  }
  const files = await readdir(dir, { recursive: true });
  for (const file of files.filter(f => f.endsWith('.json') || f.endsWith('.jsonl'))) assert.equal((await readFile(join(dir, file), 'utf8')).includes('private-fixture-key'), false);
});

test('cancellation before dispatch prevents a late production run from starting',{timeout:15000},async t=>{
  const r=runtime(t);
  r.send({v:1,type:'cancel',request_id:'c',run_id:'late'});
  assert.equal((await r.next()).data.cancelled,false);
  r.send({v:1,type:'run',request_id:'late-request',run_id:'late',session_id:'s',project_id:'p',secret:'fake',prompt:'生产',config:{url:'http://127.0.0.1:1/v1',model:'fixture'}});
  assert.equal((await r.next()).error.code,'cancelled');
});
