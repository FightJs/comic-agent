import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,readdir,rm,writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {RunCheckpoint} from '../src/checkpoints.mjs';

const input={project_id:'project',session_id:'session',run_id:'run',prompt:'synthetic request',config:{url:'http://127.0.0.1/v1',model:'fixture'},secret:'synthetic-private-key',tools:true};
async function fixture(t){const root=await mkdtemp(join(tmpdir(),'pi-checkpoint-'));t.after(()=>rm(root,{recursive:true,force:true}));return root;}
test('durable model allowance rejects the twenty-first request and cannot reset after reopening',async t=>{
 const root=await fixture(t),ledger=RunCheckpoint.start(root,input);
 for(let i=0;i<20;i++)ledger.modelRequest();
 assert.throws(()=>ledger.modelRequest(),/turn_limit/);
 assert.equal(ledger.summary().model_requests,20);
 ledger.finish('paused','turn_limit');
 const stored=RunCheckpoint.inspect(root,input);
 assert.equal(stored.status,'paused');assert.equal(stored.model_requests,20);
 assert.throws(()=>RunCheckpoint.start(root,{...input,secret:'rotated-private-key'}),/run_recorded/);
 for(const file of await readdir(join(root,'project','checkpoints')))assert.equal((await readFile(join(root,'project','checkpoints',file),'utf8')).includes('synthetic-private-key'),false);
});
test('checkpoint records fifty exact tool registrations and unresolved receipts without tool payloads',async t=>{
 const root=await fixture(t),ledger=RunCheckpoint.start(root,input);
 for(let i=0;i<50;i++){ledger.toolRequest('call'+i,'project_query',{query:'private synthetic novel text'});if(i<49)ledger.toolResult('call'+i,false);}
 assert.throws(()=>ledger.toolRequest('over','project_query',{}),/tool_limit/);
 const stored=RunCheckpoint.inspect(root,input);
 assert.equal(stored.tool_calls,50);assert.equal(stored.unresolved_tools,1);
 assert.equal(JSON.stringify(stored).includes('private synthetic novel text'),false);
 assert.throws(()=>ledger.toolRequest('call0','project_query',{}),/tool_call_conflict/);
});
test('checkpoint is project/session bound, read-only lookup does not create missing directories',async t=>{
 const root=await fixture(t);RunCheckpoint.start(root,input);
 assert.throws(()=>RunCheckpoint.inspect(root,{...input,session_id:'other'}),/checkpoint_mismatch/);
 assert.throws(()=>RunCheckpoint.inspect(root,{...input,project_id:'other'}),/checkpoint_missing/);
 assert.deepEqual(await readdir(root),['project']);
 assert.throws(()=>RunCheckpoint.start(root,{...input,run_id:'../escape'}),/invalid_request/);
});
test('new checkpoint directory entries are synced through their existing parent before registration returns',async t=>{
 const root=await fixture(t);
 const {default:fs}=await import('node:fs');const {syncBuiltinESMExports}=await import('node:module');
 const originalOpen=fs.openSync,originalSync=fs.fsyncSync,descriptors=new Map(),synced=[];
 fs.openSync=(path,...args)=>{const fd=originalOpen(path,...args);descriptors.set(fd,String(path));return fd;};
 fs.fsyncSync=fd=>{synced.push(descriptors.get(fd));return originalSync(fd);};syncBuiltinESMExports();
 try{
  RunCheckpoint.start(root,input);
  assert.deepEqual(synced.slice(0,3),[join(root,'project','checkpoints'),join(root,'project'),root]);
  const fileIndex=synced.indexOf(join(root,'project','checkpoints','run.json'));
  assert.ok(fileIndex>synced.indexOf(root));
  assert.equal(synced[fileIndex-1],'/');
 }finally{fs.openSync=originalOpen;fs.fsyncSync=originalSync;syncBuiltinESMExports();}
});
test('a registration write failure stops the live ledger even if storage later returns',async t=>{
 const root=await fixture(t),ledger=RunCheckpoint.start(root,input);
 const {renameSync}=await import('node:fs');renameSync(join(root,'project'),join(root,'project-moved'));
 assert.throws(()=>ledger.modelRequest(),/checkpoint_failed/);
 renameSync(join(root,'project-moved'),join(root,'project'));
 assert.throws(()=>ledger.modelRequest(),/checkpoint_failed/);
 assert.equal(RunCheckpoint.inspect(root,input).model_requests,0);
 assert.throws(()=>RunCheckpoint.start(root,input),/run_recorded/);
});
test('retry after a parent directory sync failure repeats the ancestor syncs before allowing registration',async t=>{
 const root=await fixture(t);const {default:fs}=await import('node:fs');const {syncBuiltinESMExports}=await import('node:module');
 const originalOpen=fs.openSync,originalSync=fs.fsyncSync,descriptors=new Map(),synced=[];let fail=true;
 fs.openSync=(path,...args)=>{const fd=originalOpen(path,...args);descriptors.set(fd,String(path));return fd;};
 fs.fsyncSync=fd=>{const path=descriptors.get(fd);synced.push(path);if(fail&&path===root){fail=false;throw Error('synthetic directory sync failure');}return originalSync(fd);};syncBuiltinESMExports();
 try{
  assert.throws(()=>RunCheckpoint.start(root,input),/synthetic directory sync failure/);
  synced.length=0;RunCheckpoint.start(root,input);
  const fileIndex=synced.indexOf(join(root,'project','checkpoints','run.json'));
  assert.ok(synced.indexOf(root)>=0&&synced.indexOf(root)<fileIndex);
  assert.equal(synced[fileIndex-1],'/');
 }finally{fs.openSync=originalOpen;fs.fsyncSync=originalSync;syncBuiltinESMExports();}
});

test('incomplete or inconsistent receipt counters cannot be inspected or resumed as a clean checkpoint',async t=>{
 const root=await fixture(t),ledger=RunCheckpoint.start(root,input);
 ledger.modelRequest();ledger.modelResponse({totalTokens:3});ledger.toolRequest('call','project_query',{});ledger.toolResult('call',false);ledger.finish('paused','manual_pause');
 const file=join(root,'project','checkpoints','run.json'),original=JSON.parse(await readFile(file,'utf8'));
 const mutations=[
  value=>{delete value.model_responses;},value=>{value.model_responses=2;},
  value=>{value.model_responses=-1;},value=>{value.model_responses=0.5;},
  value=>{delete value.known_usage_responses;},value=>{value.known_usage_responses=2;},
  value=>{value.known_usage_responses=-1;},value=>{value.tools[0].status='unknown';},
  value=>{delete value.tools[0].status;},value=>{value.tools.push({...value.tools[0]});},
  value=>{value.tools[0]=null;},value=>{value.tools[0].name='bash';},
  value=>{delete value.usage;},value=>{value.usage.totalTokens=-1;},
  value=>{value.usage.totalTokens=0;},value=>{value.tools[0].input_hash='invalid';},
 ];
 for(const mutate of mutations){
  const value=structuredClone(original);mutate(value);await writeFile(file,JSON.stringify(value));
  assert.throws(()=>RunCheckpoint.inspect(root,input),/checkpoint_invalid/);
  assert.throws(()=>RunCheckpoint.continuation(root,{...input,run_id:'child',resume_from:'run'}),/checkpoint_invalid/);
  assert.deepEqual(JSON.parse(await readFile(file,'utf8')),value,'invalid receipts must remain untouched for diagnosis');
 }
 await writeFile(file,JSON.stringify(original));assert.equal(RunCheckpoint.inspect(root,input).unreturned_models,0);
});

test('receipt summaries preserve exact host serialization hashes without exposing result bodies',async t=>{
 const {createHash}=await import('node:crypto');const root=await fixture(t),ledger=RunCheckpoint.start(root,input);
 ledger.toolRequest('receipt','project_query',{action:'source'},{session_leaf_id:'leaf',assistant_leaf_id:'assistant'});
 const result={text:'private synthetic source 中文',value:1e-7},serialized=JSON.stringify(result,null,1);
 ledger.toolResult('receipt',false,{data:result,result_json:serialized});
 const detail=RunCheckpoint.details(root,input);
 assert.equal(detail.tools[0].result_hash,createHash('sha256').update(serialized).digest('hex'));
 assert.equal(detail.tools[0].assistant_leaf_id,'assistant');
 assert.equal(JSON.stringify(detail).includes('private synthetic source'),false);
 ledger.value.tools[0].unexpected_body='private synthetic source';ledger.save();
 assert.equal(JSON.stringify(RunCheckpoint.details(root,input)).includes('private synthetic source'),false);
 delete ledger.value.tools[0].unexpected_body;ledger.save();
 detail.tools[0].status='registered';assert.equal(RunCheckpoint.details(root,input).tools[0].status,'received');
 const original=await readFile(join(root,'project','checkpoints','run.json'),'utf8');
 ledger.toolRequest('bad-receipt','project_query',{});
 assert.throws(()=>ledger.toolResult('bad-receipt',false,{data:{id:'a'},result_json:'{"id":"b"}'}),/tool_receipt_invalid/);
 assert.equal(RunCheckpoint.details(root,input).tools[1].status,'registered');
 assert.equal(original.includes('private synthetic source'),false);
});
