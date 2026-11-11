import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { mkdtempSync, rmSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=';
function runtime(t) {
  const dir=mkdtempSync(join(tmpdir(),'pi-vision-'));
  const child=spawn(process.execPath,['src/server.mjs'],{cwd:new URL('..',import.meta.url),env:{PATH:process.env.PATH,COMIC_AGENT_DATA:dir,PI_OFFLINE:'1'}});
  t.after(()=>{child.kill();rmSync(dir,{recursive:true,force:true});});
  const queue=[],waiting=[];
  createInterface({input:child.stdout}).on('line',line=>{const value=JSON.parse(line);const w=waiting.shift();w?w(value):queue.push(value);});
  return {dir,send:m=>child.stdin.write(JSON.stringify({v:1,type:'complete',request_id:m.run_id,secret:'vision-fixture-only',prompt:'核对两张图',...m})+'\n'),next:()=>queue.length?Promise.resolve(queue.shift()):new Promise(r=>waiting.push(r))};
}
test('constrained Pi vision sends actual ordered pixels and no session or tools',{timeout:20000},async t=>{
  let submitted;
  const server=createServer(async(req,res)=>{
    let body='';for await(const chunk of req)body+=chunk;submitted=JSON.parse(body);
    res.writeHead(200,{'Content-Type':'text/event-stream'});
    for(const part of [{choices:[{index:0,delta:{role:'assistant',content:'{"issues":[]}'},finish_reason:null}]},{choices:[{index:0,delta:{},finish_reason:'stop'}],usage:{prompt_tokens:15,completion_tokens:5,total_tokens:20}}])res.write(`data: ${JSON.stringify({id:'vision',object:'chat.completion.chunk',created:1,model:'fixture',...part})}\n\n`);
    res.end('data: [DONE]\n\n');
  });server.listen(0,'127.0.0.1');await once(server,'listening');t.after(()=>server.close());
  const r=runtime(t);
  r.send({run_id:'pixels',config:{model:'fixture',url:`http://127.0.0.1:${server.address().port}/v1`},images:[{mimeType:'image/png',data:png},{mimeType:'image/png',data:png}]});
  const reply=await r.next();assert.equal(reply.type,'result',JSON.stringify(reply));
  const content=submitted.messages.find(m=>m.role==='user').content;
  assert.equal(Array.isArray(content),true,'image input must reach the provider as multimodal content');
  assert.deepEqual(content.filter(p=>p.type==='image_url').map(p=>p.image_url.url),[1,2].map(()=>`data:image/png;base64,${png}`));
  assert.equal(submitted.tools?.length||0,0);assert.equal(reply.data.usage.totalTokens,20);
  assert.deepEqual(readdirSync(r.dir),[]);
});
test('vision rejects external URLs, invalid bytes and oversized images before dispatch',{timeout:15000},async t=>{
  const r=runtime(t);let i=0;
  for(const images of [[{url:'https://example.com/a.png'}],[{mimeType:'image/png',data:'YWJj'}],Array(9).fill({mimeType:'image/png',data:png}),[{mimeType:'image/svg+xml',data:png}],[{mimeType:'image/png',data:png,extra:true}]]){
    r.send({run_id:'invalid'+i++,config:{model:'fixture',url:'http://127.0.0.1:1/v1'},images});
    assert.equal((await r.next()).error?.code,'invalid_request');
  }
});
test('constrained vision never retries a provider 500 behind the one-call authorization',{timeout:20000},async t=>{
 let count=0;
 const server=createServer(async(req,res)=>{for await(const _ of req){}count++;res.writeHead(500,{'Content-Type':'application/json'});res.end('{"error":{"message":"fixture failure"}}');});
 server.listen(0,'127.0.0.1');await once(server,'listening');t.after(()=>server.close());
 const r=runtime(t);r.send({run_id:'no-retry',config:{model:'fixture',url:`http://127.0.0.1:${server.address().port}/v1`},images:[{mimeType:'image/png',data:png}]});
 assert.equal((await r.next()).type,'error');assert.equal(count,1);
});
