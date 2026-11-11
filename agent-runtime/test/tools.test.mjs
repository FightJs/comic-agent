import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ProjectBridge } from '../src/tools.mjs';

test('bridge correlates host receipts and rejects cancellation', async () => {
  const sent=[];
  const bridge=new ProjectBridge({run_id:'r',request_id:'q',session_id:'s'},value=>sent.push(value));
  const tool=bridge.tools().find(t=>t.name==='project_query');
  const result=tool.execute('call1',{action:'catalog'});
  assert.equal(sent[0].type,'tool_request');
  assert.equal(sent[0].run_id,'r');
  assert.equal(bridge.accept({run_id:'other',tool_call_id:'call1',data:{private:true}}),false);
  assert.equal(bridge.accept({run_id:'r',tool_call_id:'call1',data:{records:[{id:'a'}]}}),true);
  assert.match((await result).content[0].text,/"id":"a"/);
  const cancelled=tool.execute('call2',{action:'graph'});
  bridge.close();
  await assert.rejects(cancelled,/cancelled/);
});

test('tool limit stops the run and never dispatches a fifty-first request',async()=>{
  const sent=[];let stopped=0;
  const bridge=new ProjectBridge({run_id:'r'},m=>sent.push(m),()=>stopped++);
  const tool=bridge.tools().find(t=>t.name==='project_query');
  for(let i=0;i<50;i++){
    const pending=tool.execute('c'+i,{action:'catalog'});
    bridge.accept({run_id:'r',tool_call_id:'c'+i,data:{records:[]}});
    await pending;
  }
  await assert.rejects(tool.execute('over',{action:'catalog'}),/tool_limit/);
  assert.equal(sent.length,50);assert.equal(stopped,1);
});

test('proposal tool submits a candidate request through the host bridge',async()=>{
  const sent=[];const bridge=new ProjectBridge({run_id:'write',request_id:'r'},value=>sent.push(value));
  const writer=bridge.tools().find(t=>t.name==='propose_changes');
  assert.ok(writer);
  const result=writer.execute('proposal1',{title:'调整',changes:[{target:'record',id:'panel',patch:{description:'新画面'}}]});
  assert.equal(sent[0].name,'propose_changes');
  assert.equal(sent[0].arguments.changes[0].id,'panel');
  bridge.accept({run_id:'write',tool_call_id:'proposal1',data:{id:'saved',status:'pending'}});
  assert.match((await result).content[0].text,/pending/);
});

for(const maximum of [8])test('setup bridge stops at '+maximum+' catalog requests',async()=>{
  const sent=[];let stopped=0;
  const bridge=new ProjectBridge({run_id:'setup'},m=>sent.push(m),()=>stopped++,maximum);
  const tool=bridge.tools().find(t=>t.name==='setup_catalog');
  for(let i=0;i<maximum;i++){
    const pending=tool.execute('c'+i,{query:'流程'});
    bridge.accept({run_id:'setup',tool_call_id:'c'+i,data:{items:[]}});await pending;
  }
  await assert.rejects(tool.execute('over',{}),/tool_limit/);
  assert.equal(sent.length,maximum);assert.equal(stopped,1);
});

test('bridge sends the exact registered argument fingerprint without duplicating the payload',async()=>{
 const {createHash}=await import('node:crypto');const sent=[];
 const bridge=new ProjectBridge({run_id:'r'},m=>sent.push(m));const args={action:'graph',query:'中文',number:1e-7};
 const result=bridge.tools().find(t=>t.name==='project_query').execute('hash-call',args);
 assert.equal(sent[0].input_hash,createHash('sha256').update(JSON.stringify(args)).digest('hex'));
 bridge.accept({run_id:'r',tool_call_id:'hash-call',data:{records:[]}});await result;
});
