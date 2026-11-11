import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {mkdtempSync,mkdirSync,readFileSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
import {SessionManager} from '@earendil-works/pi-coding-agent';
import {RunCheckpoint} from '../src/checkpoints.mjs';
const hash=value=>createHash('sha256').update(value).digest('hex');

test('private recovery command repairs a crash without a provider or replay and is idempotent',{timeout:15000},async t=>{
 const root=mkdtempSync(join(tmpdir(),'pi-recovery-protocol-'));
 const input={project_id:'project',session_id:'session',run_id:'run',prompt:'synthetic',config:{model:'fixture'}};
 const directory=join(root,'project','sessions','session');mkdirSync(directory,{recursive:true});
 const manager=SessionManager.create(root,directory);manager.appendMessage({role:'user',content:'synthetic',timestamp:Date.now()});
 const checkpoint=RunCheckpoint.start(root,input);checkpoint.bindSession(manager);
 const args={action:'catalog'},leaf=manager.appendMessage({role:'assistant',content:[{type:'toolCall',id:'read',name:'project_query',arguments:args}],api:'openai-completions',provider:'fixture',model:'fixture',usage:{input:1,output:1,cacheRead:0,cacheWrite:0,totalTokens:2,cost:{total:0}},stopReason:'toolUse',timestamp:Date.now()});
 checkpoint.modelRequest();checkpoint.modelResponse({totalTokens:2});checkpoint.toolRequest('read','project_query',args,{assistant_leaf_id:leaf,session_leaf_id:leaf});
 const before=readFileSync(manager.getSessionFile(),'utf8');
 const child=spawn(process.execPath,['src/server.mjs'],{cwd:new URL('..',import.meta.url),env:{PATH:process.env.PATH,COMIC_AGENT_DATA:root,PI_OFFLINE:'1'}});
 t.after(()=>{child.kill();rmSync(root,{recursive:true,force:true});});
 const queue=[],waiters=[];createInterface({input:child.stdout}).on('line',line=>{const value=JSON.parse(line),next=waiters.shift();if(next)next(value);else queue.push(value);});
 const next=()=>queue.length?Promise.resolve(queue.shift()):new Promise(resolve=>waiters.push(resolve));
 const send=value=>child.stdin.write(JSON.stringify(value)+'\n');
 const serialized='{ "records": [], "note": "private synthetic result" }';
 const message={v:1,type:'recover_tools',request_id:'restore',...input,recovery_id:'repair',receipts:[{call_id:'read',name:'project_query',node_input_hash:hash(JSON.stringify(args)),result_json:serialized,result_hash:hash(serialized)}]};
 send(message);const result=await next();assert.equal(result.type,'result',JSON.stringify(result));
 assert.equal(result.data.project_id,input.project_id);assert.equal(result.data.checkpoint.status,'paused');assert.equal(result.data.checkpoint.unresolved_tools,0);assert.equal(result.data.checkpoint.model_requests,1);
 assert.equal(JSON.stringify(result).includes('private synthetic result'),false);
 const saved=readFileSync(manager.getSessionFile(),'utf8');assert.ok(saved.startsWith(before));
 send({...message,request_id:'retry'});assert.deepEqual((await next()).data,result.data);assert.equal(readFileSync(manager.getSessionFile(),'utf8'),saved);
 send({v:1,type:'health',request_id:'healthy'});assert.equal((await next()).data.protocol,1);
 // Both JSONL messages dispatch before run() reaches its first asynchronous setup.
 send({v:1,type:'run',request_id:'live',...input,run_id:'live',config:{model:'fixture',url:'http://127.0.0.1:1/v1'},secret:'fake',tools:false,start_paused:true});
 send({...message,request_id:'locked'});
 const replies=new Map();while(!replies.has('live')||!replies.has('locked')){const reply=await next();if(reply.type!=='event')replies.set(reply.request_id,reply);}
 assert.equal(replies.get('locked').error.code,'session_busy');
 assert.equal(replies.get('live').data.checkpoint.model_requests,0);

});
