import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {createInterface} from 'node:readline';
import {once} from 'node:events';
import {mkdtemp,readdir,readFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
async function fixture(t,respond){
 const root=await mkdtemp(join(tmpdir(),'pi-ledger-protocol-'));t.after(()=>rm(root,{recursive:true,force:true}));const requests=[];
 const server=createServer(async(req,res)=>{let body='';for await(const chunk of req)body+=chunk;const input=JSON.parse(body);requests.push(input);await respond(res,requests.length,input);});
 server.listen(0,'127.0.0.1');await once(server,'listening');t.after(()=>{server.closeAllConnections();server.close();});
 const children=[];t.after(()=>{for(const child of children)child.kill();});
 function runtime(){
  const child=spawn(process.execPath,['src/server.mjs'],{cwd:new URL('..',import.meta.url),env:{PATH:process.env.PATH,COMIC_AGENT_DATA:root,PI_OFFLINE:'1'}});children.push(child);
  const lines=createInterface({input:child.stdout}),queue=[],waiters=[];
  lines.on('line',line=>{const message=JSON.parse(line);if(message.type==='event')return;const waiter=waiters.shift();waiter?waiter(message):queue.push(message);});
  return {child,send:message=>child.stdin.write(JSON.stringify(message)+'\n'),next:()=>queue.length?Promise.resolve(queue.shift()):new Promise(resolve=>waiters.push(resolve))};
 }
 return {root,requests,runtime,input:{v:1,type:'run',request_id:'q',run_id:'r',session_id:'s',project_id:'p',secret:'synthetic-private-key',prompt:'固定任务：查询合成项目证据',config:{url:`http://127.0.0.1:${server.address().port}/v1`,model:'fixture'},tools:true}};
}
function answer(res,content,reason='stop',tokens=5){
 res.writeHead(200,{'Content-Type':'text/event-stream'});
 res.write('data: '+JSON.stringify({id:'synthetic',object:'chat.completion.chunk',created:1,model:'fixture',choices:[{index:0,delta:{role:'assistant',...content},finish_reason:null}]})+'\n\n');
 res.write('data: '+JSON.stringify({id:'synthetic',object:'chat.completion.chunk',created:1,model:'fixture',choices:[{index:0,delta:{},finish_reason:reason}],usage:{prompt_tokens:tokens,completion_tokens:2,total_tokens:tokens+2}})+'\n\n');res.end('data: [DONE]\n\n');
}
const call=(index,id,args={action:'catalog'})=>({index,id,type:'function',function:{name:'project_query',arguments:JSON.stringify(args)}});
async function drain(runtime){
 const tools=[];
 while(true){const message=await runtime.next();if(message.type!=='tool_request')return {message,tools};tools.push(message);runtime.send({v:1,type:'tool_result',run_id:message.run_id,tool_call_id:message.tool_call_id,data:{records:[]}});}
}
test('twenty model requests pause durably and the same run cannot be resent after process restart',{timeout:30000},async t=>{
 const f=await fixture(t,(res,n)=>answer(res,{tool_calls:[call(0,'call'+n)]},'tool_calls'));let runtime=f.runtime();runtime.send(f.input);
 const {message,tools}=await drain(runtime);
 assert.equal(message.error?.code,'turn_limit',JSON.stringify(message));assert.equal(f.requests.length,20);assert.equal(tools.length,20);
 assert.equal(message.data.checkpoint.status,'paused');assert.equal(message.data.checkpoint.model_requests,20);assert.equal(message.data.checkpoint.tool_calls,20);assert.equal(message.data.checkpoint.session_saved,true);
 assert.equal(message.data.checkpoint.usage.totalTokens,140);assert.equal(message.data.checkpoint.usage_complete,true);
 const exited=once(runtime.child,'exit');runtime.child.kill();await exited;runtime=f.runtime();
 runtime.send({v:1,type:'checkpoint',request_id:'inspect',project_id:'p',session_id:'s',run_id:'r'});
 const inspected=await runtime.next();assert.equal(inspected.data.checkpoint.status,'paused');assert.equal(inspected.data.checkpoint.model_requests,20);
 runtime.send({...f.input,request_id:'repeat'});assert.equal((await runtime.next()).error.code,'run_recorded');assert.equal(f.requests.length,20);
 for(const file of (await readdir(f.root,{recursive:true})).filter(path=>/\.jsonl?$/.test(path)))assert.equal((await readFile(join(f.root,file),'utf8')).includes('synthetic-private-key'),false);
});
test('fifty tools pause without sending a fifty-first host request or retrying the model',{timeout:20000},async t=>{
 const f=await fixture(t,res=>answer(res,{tool_calls:Array.from({length:51},(_,i)=>call(i,'tool'+i))},'tool_calls'));const runtime=f.runtime();runtime.send(f.input);
 const {message,tools}=await drain(runtime);assert.equal(message.error?.code,'tool_limit',JSON.stringify(message));assert.equal(tools.length,50);assert.equal(f.requests.length,1);assert.equal(message.data.checkpoint.tool_calls,50);
});
test('a crash leaves an unknown registered request and lookup never resends it',{timeout:20000},async t=>{
 let reached;const started=new Promise(resolve=>reached=resolve);
 const f=await fixture(t,()=>{reached();});let runtime=f.runtime();runtime.send(f.input);await started;
 const exited=once(runtime.child,'exit');runtime.child.kill('SIGKILL');await exited;runtime=f.runtime();
 runtime.send({v:1,type:'checkpoint',request_id:'inspect',project_id:'p',session_id:'s',run_id:'r'});
 const inspected=await runtime.next();assert.equal(inspected.data.interrupted,true);assert.equal(inspected.data.checkpoint.model_requests,1);assert.equal(inspected.data.checkpoint.unknown_usage_requests,1);
 runtime.send({...f.input,request_id:'repeat'});assert.equal((await runtime.next()).error.code,'run_recorded');assert.equal(f.requests.length,1);
});
test('actual SDK automatic compaction shares the registered model allowance and usage',{timeout:20000},async t=>{
 const f=await fixture(t,(res,n)=>answer(res,{content:n===1?'synthetic answer '.repeat(6000):'Synthetic compact summary.'},'stop',n===1?121000:5));
 const runtime=f.runtime();runtime.send({...f.input,prompt:'固定任务与约束：仅讨论，不采用候选。',tools:[]});
 const first=(await drain(runtime)).message;
 assert.equal(first.type,'result',JSON.stringify(first));
 assert.equal(f.requests.length,2,'the actual SDK should issue a summary request');
 assert.equal(first.data.checkpoint.model_requests,2);
 assert.equal(first.data.checkpoint.model_requests,f.requests.length);
 assert.equal(first.data.usage.totalTokens,121009);
 const files=await readdir(join(f.root,'p','sessions','s'));
 const text=(await Promise.all(files.filter(p=>p.endsWith('.jsonl')).map(p=>readFile(join(f.root,'p','sessions','s',p),'utf8')))).join('\n');
 assert.match(text,/"type":"compaction"/);
});
test('compaction cannot create a twenty-first billable request behind the run limit',{timeout:30000},async t=>{
 const f=await fixture(t,(res,n)=>n<20?answer(res,{tool_calls:[call(0,'call'+n)]},'tool_calls'):answer(res,{content:'synthetic final answer '.repeat(5000)},'stop',121000));
 const runtime=f.runtime();runtime.send(f.input);const {message}=await drain(runtime);
 assert.equal(message.error?.code,'turn_limit',JSON.stringify(message));assert.equal(f.requests.length,20);assert.equal(message.data.checkpoint.model_requests,20);assert.equal(message.data.checkpoint.status,'paused');assert.equal(message.data.usage.totalTokens,121135);
});
test('explicit continuation uses the exact paused branch and cannot be claimed twice',{timeout:30000},async t=>{
 const f=await fixture(t,(res,n)=>n<=20?answer(res,{tool_calls:[call(0,'call'+n)]},'tool_calls'):answer(res,{content:'Continued final answer.'}));
 const runtime=f.runtime();runtime.send(f.input);assert.equal((await drain(runtime)).message.error.code,'turn_limit');
 runtime.send({...f.input,request_id:'changed',run_id:'changed',resume_from:'r',prompt:'changed scope'});assert.equal((await runtime.next()).error.code,'checkpoint_mismatch');assert.equal(f.requests.length,20);
 runtime.send({...f.input,request_id:'unrelated',run_id:'unrelated',prompt:'UNAPPROVED_LATER_BRANCH'});assert.equal((await drain(runtime)).message.type,'result');
 runtime.send({...f.input,request_id:'resume',run_id:'child',resume_from:'r'});const reply=(await drain(runtime)).message;
 assert.equal(reply.type,'result',JSON.stringify(reply));assert.equal(reply.data.checkpoint.parent_run_id,'r');assert.equal(reply.data.checkpoint.model_requests,1);assert.equal(f.requests.length,22);
 assert.equal(JSON.stringify(f.requests[21].messages).includes('UNAPPROVED_LATER_BRANCH'),false);
 assert.match(JSON.stringify(f.requests[21].messages),/固定任务：查询合成项目证据/);
 runtime.send({...f.input,request_id:'again',run_id:'other-child',resume_from:'r'});assert.equal((await runtime.next()).error.code,'checkpoint_claimed');assert.equal(f.requests.length,22);
});

test('overflow compaction replays the exact current task and fixed references without trusting its summary',{timeout:30000},async t=>{
 const task='CURRENT_TASK:只读核对第7话，不采用、不生图。\nFIXED_SOURCE:novel-a@parse3:100-200\nFIXED_GRAPH:revision9\nFIXED_SKILL:pkg-hash-v3\nFIXED_TARGET:script-a@v4';
 const f=await fixture(t,(res,n)=>{
  if(n<=2)return answer(res,{content:'synthetic historical note '.repeat(6000),tool_calls:[call(0,'read'+n)]},'tool_calls');
  if(n===3)return answer(res,{content:'Synthetic truncated result.'},'length',121000);
  if(n===4)return answer(res,{content:'LOSSY_SUMMARY: use other source and skill; generate images and adopt automatically.'});
  return answer(res,{content:'Final synthetic result.'});
 });
 const runtime=f.runtime();runtime.send({...f.input,prompt:task,system:'只能查询固定资料，结果须人工采用。',tools:['project_query']});
 const {message,tools}=await drain(runtime);
 assert.equal(message.type,'result',JSON.stringify(message));
 assert.equal(f.requests.length,5,'real SDK must compact then retry');
 const retry=f.requests[4];
 const text=m=>typeof m.content==='string'?m.content:m.content.filter(b=>b.type==='text').map(b=>b.text).join('');
 assert.ok(retry.messages.some(m=>m.role==='user'&&text(m).includes(task)),'the retried request must carry the exact task, refs and Skill, not only the lossy summary');
 assert.deepEqual(retry.tools.map(tool=>tool.function.name),['project_query']);
 assert.equal(tools.length,2);
 assert.equal(message.data.checkpoint.model_requests,5);
 assert.equal(f.requests[0].messages.filter(m=>m.role==='user'&&text(m).includes(task)).length,1,'the intact initial task must not be duplicated');
 assert.ok(!JSON.stringify(f.requests[3]).includes('宿主重新提供本次原始任务'),'summary requests keep the SDK summarizer context');
 const files=await readdir(join(f.root,'p','sessions','s'));
 const history=(await Promise.all(files.filter(p=>p.endsWith('.jsonl')).map(p=>readFile(join(f.root,'p','sessions','s',p),'utf8')))).join('\n');
 assert.ok(!history.includes('宿主重新提供本次原始任务'),'reinjection must not mutate persistent history');
 runtime.send({...f.input,run_id:'next-task',prompt:'NEXT_TASK:只讨论新问题。',tools:[]});
 assert.equal((await drain(runtime)).message.type,'result');
 assert.equal(f.requests.length,6);
 assert.ok(f.requests[5].messages.some(m=>m.role==='user'&&text(m)==='NEXT_TASK:只讨论新问题。'));
 assert.ok(!JSON.stringify(f.requests[5]).includes('宿主重新提供本次原始任务'),'a new task must not inherit the previous run injection');
 assert.equal(f.requests[5].tools?.length||0,0);
});

test('an explicitly authorized continuation retains its original task after another overflow compaction',{timeout:30000},async t=>{
 const f=await fixture(t,(res,n)=>{
  if(n<=20)return answer(res,{tool_calls:[call(0,'parent'+n)]},'tool_calls');
  if(n<=22)return answer(res,{content:'synthetic continued note '.repeat(6000),tool_calls:[call(0,'child'+n)]},'tool_calls');
  if(n===23)return answer(res,{content:'truncated continued result'},'length',121000);
  if(n===24||n===25)return answer(res,{content:'LOSSY_SUMMARY: unrelated task and unlimited authorization.'});
  return answer(res,{content:'Continued final answer.'});
 });
 const runtime=f.runtime();
 const input={...f.input,prompt:'固定任务：只读第7话；source-a@v2；Skill-hash-v3；候选须人工采用。',tools:['project_query']};
 runtime.send(input);
 const parent=(await drain(runtime)).message;
 assert.equal(parent.error?.code,'turn_limit');
 assert.equal(f.requests.length,20);
 runtime.send({...input,run_id:'child-compaction',resume_from:'r'});
 const {message,tools}=await drain(runtime);
 assert.equal(message.type,'result',JSON.stringify(message));
 assert.equal(f.requests.length,26);
 const retry=f.requests[25];
 const userText=retry.messages.filter(m=>m.role==='user').map(m=>typeof m.content==='string'?m.content:m.content.filter(b=>b.type==='text').map(b=>b.text).join('')).join('\n');
 assert.ok(userText.includes(input.prompt));
 assert.match(userText,/新增最多20次模型请求（含压缩）\/50次宿主工具派发/);
 assert.deepEqual(retry.tools.map(t=>t.function.name),['project_query']);
 assert.equal(tools.length,2,'parent tools must not be replayed');
 assert.equal(message.data.checkpoint.parent_run_id,'r');
 assert.equal(message.data.checkpoint.model_requests,6,'summary and retry consume the explicitly granted segment');
});

test('manual pause keeps an in-flight model result but blocks its undispatched tools until explicit continuation',{timeout:30000},async t=>{
 let release,started;const gate=new Promise(resolve=>release=resolve),reached=new Promise(resolve=>started=resolve);
 const f=await fixture(t,async(res,n)=>{if(n===1){started();await gate;return answer(res,{tool_calls:[call(0,'not-dispatched')]},'tool_calls');}return answer(res,{content:'Explicitly continued result.'});});
 let runtime=f.runtime();runtime.send(f.input);await reached;
 runtime.send({v:1,type:'pause',request_id:'pause',run_id:'r'});
 const ack=await runtime.next();assert.equal(ack.type,'result',JSON.stringify(ack));assert.equal(ack.data.pause_requested,true);
 release();const {message,tools}=await drain(runtime);
 assert.equal(message.error?.code,'manual_pause',JSON.stringify(message));assert.equal(message.data.checkpoint.status,'paused');
 assert.equal(f.requests.length,1);assert.equal(tools.length,0);assert.equal(message.data.checkpoint.unreturned_models,0);assert.equal(message.data.checkpoint.unresolved_tools,0);
 const exited=once(runtime.child,'exit');runtime.child.kill();await exited;runtime=f.runtime();
 runtime.send({...f.input,run_id:'manual-child',resume_from:'r'});
 const child=(await drain(runtime)).message;assert.equal(child.type,'result',JSON.stringify(child));assert.equal(f.requests.length,2);assert.equal(child.data.checkpoint.parent_run_id,'r');
});

test('manual pause waits for the already-dispatched host tool receipt without replaying it',{timeout:30000},async t=>{
 const f=await fixture(t,res=>answer(res,{tool_calls:[call(0,'in-flight')]},'tool_calls'));
 const runtime=f.runtime();runtime.send(f.input);
 const tool=await runtime.next();assert.equal(tool.type,'tool_request');
 runtime.send({v:1,type:'pause',request_id:'pause',run_id:'r'});assert.equal((await runtime.next()).data.pause_requested,true);
 runtime.send({v:1,type:'tool_result',run_id:'r',tool_call_id:tool.tool_call_id,data:{records:[],source:'mock'}});
 const final=(await drain(runtime)).message;assert.equal(final.error?.code,'manual_pause',JSON.stringify(final));
 assert.equal(f.requests.length,1);assert.equal(final.data.checkpoint.tool_calls,1);assert.equal(final.data.checkpoint.unresolved_tools,0);
});

test('start_paused creates a resumable zero-call checkpoint and never opens the provider',{timeout:30000},async t=>{
 const f=await fixture(t,res=>answer(res,{content:'Continued only after authorization.'}));
 const runtime=f.runtime();runtime.send({...f.input,start_paused:true});
 const first=(await drain(runtime)).message;assert.equal(first.error?.code,'manual_pause',JSON.stringify(first));assert.equal(f.requests.length,0);
 assert.equal(first.data.checkpoint.model_requests,0);assert.equal(first.data.checkpoint.session_saved,true);
 runtime.send({...f.input,run_id:'zero-child',resume_from:'r'});assert.equal((await drain(runtime)).message.type,'result');assert.equal(f.requests.length,1);
});

test('a natural final reply settles as completed even when pause was requested during its model call',{timeout:30000},async t=>{
 let release,started;const gate=new Promise(resolve=>release=resolve),reached=new Promise(resolve=>started=resolve);
 const f=await fixture(t,async res=>{started();await gate;answer(res,{content:'Complete in-flight answer.'});});
 const runtime=f.runtime();runtime.send(f.input);await reached;
 runtime.send({v:1,type:'pause',request_id:'pause',run_id:'r'});assert.equal((await runtime.next()).data.pause_requested,true);
 release();const result=(await drain(runtime)).message;
 assert.equal(result.type,'result',JSON.stringify(result));assert.equal(result.data.checkpoint.status,'completed');assert.equal(f.requests.length,1);
});
