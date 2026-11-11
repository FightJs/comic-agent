import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import {mkdtemp,readdir,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

for(const command of ['run','complete','setup'])for(const mode of ['error','stream'])test(`${command} provider ${mode} credential echo is absent from protocol and Pi session`,{timeout:15000},async t=>{
  const secret='private-fixture-credential-123456';
  const dir=await mkdtemp(join(tmpdir(),'pi-privacy-'));t.after(()=>rm(dir,{recursive:true,force:true}));
  const server=createServer(async(req,res)=>{
    for await(const _ of req){}
    if(mode==='error'){res.writeHead(401,{'Content-Type':'application/json'});res.end(JSON.stringify({error:{message:'invalid key '+secret,type:'invalid_api_key'}}));return;}
    res.writeHead(200,{'Content-Type':'text/event-stream'});
    for(const content of ['正常文字 ',secret.slice(0,12),secret.slice(12),' 已结束'])res.write('data: '+JSON.stringify({id:'echo',object:'chat.completion.chunk',created:1,model:'fixture',choices:[{index:0,delta:{content},finish_reason:null}]})+'\n\n');
    res.write('data: '+JSON.stringify({id:'echo',object:'chat.completion.chunk',created:1,model:'fixture',choices:[{index:0,delta:{},finish_reason:'stop'}]})+'\n\n');res.end('data: [DONE]\n\n');
  });server.listen(0,'127.0.0.1');await once(server,'listening');t.after(()=>server.close());
  const child=spawn(process.execPath,['src/server.mjs'],{cwd:new URL('..',import.meta.url),env:{PATH:process.env.PATH,PI_OFFLINE:'1',COMIC_AGENT_DATA:dir}});t.after(()=>child.kill());
  const lines=createInterface({input:child.stdout});const output=[];
  child.stdin.write(JSON.stringify({v:1,type:command,request_id:'q',run_id:'r',session_id:'s',project_id:'p',secret,prompt:'回答测试',config:{url:`http://127.0.0.1:${server.address().port}/v1`,model:'fixture'}})+'\n');
  for await(const line of lines){const value=JSON.parse(line);output.push(value);if(value.type!=='event')break;}
  if(mode==='error')assert.equal(output.at(-1).error.code,'provider_error');
  else assert.equal(output.at(-1).type,'result');
  assert.equal(JSON.stringify(output).includes(secret),false);
  assert.equal(output.filter(v=>v.event==='text_delta').map(v=>v.delta).join('').includes(secret),false);
  if(command==='complete' && mode==='stream')assert.equal(output.at(-1).data.text,'正常文字 [REDACTED] 已结束');
  const files=await readdir(dir,{recursive:true});
  if(command==='complete')assert.equal(files.length,0);
  if(command==='setup')assert.equal(files.filter(p=>p.endsWith('.jsonl')||p.endsWith('.json')).length,0);
  for(const path of files.filter(p=>p.endsWith('.jsonl')||p.endsWith('.json')))assert.equal((await readFile(join(dir,path),'utf8')).includes(secret),false,`credential persisted in ${path}`);
});

test('credential filter handles every split, repeated matches and normal streaming',async()=>{
  const {credentialFilter}=await import('../src/model.mjs');
  const secret='fixture-private-key';
  for(let split=0;split<=secret.length;split++){
    const filter=credentialFilter(secret);
    assert.equal(filter('ordinary text '),'ordinary text ');
    const result=filter(secret.slice(0,split))+filter(secret.slice(split)+' '+secret+' done')+filter('',true);
    assert.equal(result,'[REDACTED] [REDACTED] done');
  }
  const filter=credentialFilter(secret);
  assert.equal(filter('fix'),'');
  assert.equal(filter('ation'),'fixation');
  assert.equal(filter('fix'),'');
  assert.equal(filter('',true),'fix');
});
