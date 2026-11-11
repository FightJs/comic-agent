// Offline receipt repair. The caller must hold the project/session lock.
import {readFileSync,writeFileSync,openSync,closeSync,fsyncSync,renameSync,existsSync,realpathSync} from 'node:fs';
import {resolve,join,dirname} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {SessionManager} from '@earendil-works/pi-coding-agent';
import {RunCheckpoint} from './checkpoints.mjs';
const hash=s=>createHash('sha256').update(s).digest('hex');
const fail=()=>{throw Error('recovery_conflict');};
const sync=path=>{const fd=openSync(path,'r');try{fsyncSync(fd);}finally{closeSync(fd);}};
function atomic(path,value){const temp=path+'.'+randomUUID()+'.tmp';const fd=openSync(temp,'wx',0o600);try{writeFileSync(fd,JSON.stringify(value));fsyncSync(fd);}finally{closeSync(fd);}renameSync(temp,path);sync(dirname(path));}
function read(path){try{return JSON.parse(readFileSync(path,'utf8'));}catch{fail();}}
export function recoverTools(root,input){
 try{return recover(root,input);}catch(error){if(error.message.startsWith('recovery_'))throw error;throw Error('recovery_failed');}
}
function recover(root,input){
 root=realpathSync(resolve(root));
 if(!/^[a-zA-Z0-9_-]{1,100}$/.test(input.recovery_id||'')||!Array.isArray(input.receipts)||input.receipts.length>50)fail();
 const ledger=RunCheckpoint.load(root,input),current=ledger.value;
 const journalPath=join(dirname(ledger.path),input.run_id+'.recovery.json');
 const snapshotPath=join(dirname(ledger.path),input.run_id+'.recovery-snapshot.json');
 const receipts=new Map();
 for(const receipt of input.receipts){if(!receipt||typeof receipt.call_id!=='string'||receipts.has(receipt.call_id)||typeof receipt.result_json!=='string'||receipt.result_json.length>2000000||hash(receipt.result_json)!==receipt.result_hash)fail();let data;try{data=JSON.parse(receipt.result_json);}catch{fail();}receipts.set(receipt.call_id,{...receipt,text:JSON.stringify(data)});}
 const evidence=hash(JSON.stringify([...receipts.values()].map(r=>[r.call_id,r.name,r.node_input_hash,r.result_hash]).sort((a,b)=>a[0].localeCompare(b[0]))));
 let journal=existsSync(journalPath)?read(journalPath):null;
 if(journal&&(journal.recovery_id!==input.recovery_id||journal.evidence!==evidence))fail();
 const original=journal?read(snapshotPath):structuredClone(current);
 if(journal&&hash(JSON.stringify(original))!==journal.snapshot_hash)fail();
 if(['project_id','session_id','run_id'].some(k=>original[k]!==input[k])||['cancelled','completed','continued'].includes(original.status)||original.continued_by||original.model_requests!==original.model_responses||!original.tools.some(t=>t.status==='registered'))fail();
 if(!journal&&existsSync(snapshotPath)){if(hash(JSON.stringify(read(snapshotPath)))!==hash(JSON.stringify(original)))fail();}
 if(journal){const expected=journal.published_hash;if(hash(JSON.stringify(current))!==journal.snapshot_hash&&(!expected||hash(JSON.stringify(current))!==expected))fail();}
 const registered=original.tools.filter(t=>t.status==='registered');
 const aid=registered[0].assistant_leaf_id;
 if(!aid||registered.some(t=>t.assistant_leaf_id!==aid))fail();
 const file=resolve(root,original.session_file||'.'),sessionDir=realpathSync(join(root,input.project_id,'sessions',input.session_id));
 if(sessionDir!==resolve(root,input.project_id,'sessions',input.session_id)||!file.startsWith(sessionDir+'/')||!file.endsWith('.jsonl')||!existsSync(file)||realpathSync(file)!==file)fail();
 const raw=readFileSync(file,'utf8');if(!raw.endsWith('\n'))fail();
 let entries;try{entries=raw.trimEnd().split('\n').map(line=>JSON.parse(line));}catch{fail();}
 if(entries[0]?.type!=='session')fail();
 const ids=new Set();for(const e of entries.slice(1)){if(!e.id||ids.has(e.id)||(e.parentId!==null&&e.parentId!==undefined&&!ids.has(e.parentId)))fail();ids.add(e.id);}
 const index=entries.findIndex(e=>e.id===aid),assistant=entries[index];
 if(index<1||assistant.type!=='message'||assistant.message?.role!=='assistant'||entries.slice(index+1).some(e=>e.message?.role==='assistant'))fail();
 const calls=assistant.message.content?.filter(c=>c.type==='toolCall');if(!calls?.length)fail();
 const group=original.tools.filter(t=>t.assistant_leaf_id===aid);
 if(group.length!==calls.length||receipts.size!==calls.length||new Set(calls.map(c=>c.id)).size!==calls.length)fail();
 for(const call of calls){const tool=group.find(t=>t.id===call.id),r=receipts.get(call.id);if(!tool||!r||tool.status==='rejected'||tool.name!==call.name||r.name!==call.name||tool.input_hash!==hash(JSON.stringify(call.arguments))||r.node_input_hash!==tool.input_hash)fail();if(tool.status==='received'&&(tool.result_encoding!=='host_json'||tool.result_hash!==r.result_hash))fail();}
 // Only an exact linear suffix of tool results is repairable, never an uncertain branch.
 let leaf=aid;const present=new Set();
 for(const e of entries.slice(index+1)){const r=receipts.get(e.message?.toolCallId);if(e.type!=='message'||e.message?.role!=='toolResult'||e.parentId!==leaf||!r||present.has(r.call_id)||e.message.toolName!==r.name||e.message.isError||JSON.stringify(e.message.content)!==JSON.stringify([{type:'text',text:r.text}]))fail();if(e.message.details?.pi_recovery_id&&e.message.details.pi_recovery_id!==input.recovery_id)fail();present.add(r.call_id);leaf=e.id;}
 const suffixIds=new Set([aid,...entries.slice(index+1).map(e=>e.id)]);
 const byId=new Map(entries.slice(1).map(e=>[e.id,e]));
 const ancestors=new Set();let ancestor=assistant.parentId;while(ancestor){ancestors.add(ancestor);ancestor=byId.get(ancestor)?.parentId;}
 if(!suffixIds.has(original.leaf_id)){
  if(!ancestors.has(original.leaf_id)||group.some(t=>!suffixIds.has(t.session_leaf_id)))fail();
 }
 if(group.some(t=>t.session_leaf_id!==undefined&&!suffixIds.has(t.session_leaf_id)))fail();
 if(!journal){
  if(!existsSync(snapshotPath))atomic(snapshotPath,original);else{sync(snapshotPath);sync(dirname(snapshotPath));}
  journal={v:1,recovery_id:input.recovery_id,evidence,snapshot_hash:hash(JSON.stringify(original))};atomic(journalPath,journal);
 }
 if(journal.published_hash&&hash(JSON.stringify(current))===journal.published_hash){sync(file);sync(dirname(file));sync(ledger.path);sync(dirname(ledger.path));return {project_id:original.project_id,session_id:original.session_id,run_id:original.run_id,recovery_id:input.recovery_id,checkpoint:ledger.summary()};}
 const manager=SessionManager.open(file);manager.branch(leaf);
 for(const call of calls){if(present.has(call.id))continue;const r=receipts.get(call.id);leaf=manager.appendMessage({role:'toolResult',toolCallId:call.id,toolName:call.name,content:[{type:'text',text:r.text}],details:{pi_recovery_id:input.recovery_id},isError:false,timestamp:Date.now()});}
 sync(file);sync(dirname(file));
 const next=structuredClone(original);next.status='paused';next.reason='tools_recovered';next.leaf_id=leaf;next.updated=journal.updated||new Date().toISOString();
 for(const tool of next.tools){if(tool.assistant_leaf_id===aid){tool.status='received';tool.result_hash=receipts.get(tool.id).result_hash;tool.result_encoding='host_json';}}
 journal.updated=next.updated;journal.published_hash=hash(JSON.stringify(next));atomic(journalPath,journal);
 atomic(ledger.path,next);ledger.value=next;
 return {project_id:original.project_id,session_id:original.session_id,run_id:original.run_id,recovery_id:input.recovery_id,checkpoint:ledger.summary()};
}
