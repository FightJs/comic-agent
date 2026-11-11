// Durable dispatch registrations, never provider credentials or tool payloads.
import {mkdirSync,openSync,closeSync,writeFileSync,readFileSync,renameSync,unlinkSync,fsyncSync,existsSync,statSync} from 'node:fs';
import {join,relative,dirname,resolve} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {isDeepStrictEqual} from 'node:util';
const validId=value=>typeof value==='string'&&/^[a-zA-Z0-9_-]{1,100}$/.test(value);
const binding=input=>[input.prompt,input.system||'',{url:input.config?.url?.replace(/\/+$/,''),model:input.config?.model,api:input.config?.api||'openai-completions'},input.tools??false];
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
function validReceipts(value){
 if(!value||typeof value!=='object'||Array.isArray(value))return false;
 const {model_requests:requests,model_responses:responses,known_usage_responses:known,tools,usage}=value;
 if(![requests,responses,known].every(Number.isInteger)||requests<0||requests>20||responses<0||responses>requests||known<0||known>responses)return false;
 if(!Array.isArray(tools)||tools.length>50)return false;
 const ids=new Set();
 for(const tool of tools){
  if(!tool||typeof tool!=='object'||typeof tool.id!=='string'||tool.id.length<1||tool.id.length>200||ids.has(tool.id)||!['project_query','propose_changes','propose_image','propose_style_tests'].includes(tool.name)||!['registered','received','rejected'].includes(tool.status)||typeof tool.input_hash!=='string'||!/^[a-f0-9]{64}$/.test(tool.input_hash))return false;
  if(tool.result_hash!==undefined&&(typeof tool.result_hash!=='string'||!/^[a-f0-9]{64}$/.test(tool.result_hash)))return false;
  for(const key of ['session_leaf_id','assistant_leaf_id'])if(tool[key]!==undefined&&(typeof tool[key]!=='string'||tool[key].length<1||tool[key].length>200))return false;
  if(tool.result_encoding!==undefined&&!['host_json','local_json'].includes(tool.result_encoding))return false;
  if((tool.result_hash!==undefined)!==(tool.result_encoding!==undefined)||tool.status==='registered'&&tool.result_hash!==undefined)return false;
  ids.add(tool.id);
 }
 return usage&&typeof usage==='object'&&['input','output','cacheRead','cacheWrite','totalTokens'].every(key=>Number.isFinite(usage[key])&&usage[key]>=0)&&(known===0||usage.totalTokens>0);
}

function location(root,input){
 if(![input.project_id,input.session_id,input.run_id].every(validId))throw Error('invalid_request');
 return join(root,input.project_id,'checkpoints',input.run_id+'.json');
}
function syncDirectory(directory){const fd=openSync(directory,'r');try{fsyncSync(fd);}finally{closeSync(fd);}}
export class RunCheckpoint{
 static start(root,input){
  root=resolve(root);
  const path=location(root,input),directory=join(root,input.project_id,'checkpoints');
  mkdirSync(directory,{recursive:true,mode:0o700});
  // A failed earlier initialization may have left any ancestor unsynced.
  for(let current=directory;;current=dirname(current)){syncDirectory(current);if(current===dirname(current))break;}
  const value={v:1,project_id:input.project_id,session_id:input.session_id,run_id:input.run_id,status:'running',reason:null,binding_version:2,input_hash:hash(binding(input)),parent_run_id:input.resume_from||null,continued_by:null,model_requests:0,model_responses:0,known_usage_responses:0,usage:{input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,cost:null},tools:[],session_file:null,start_leaf_id:null,leaf_id:null,updated:new Date().toISOString()};
  let fd;
  try{fd=openSync(path,'wx',0o600);}catch(e){if(e.code==='EEXIST')throw Error('run_recorded');throw Error('checkpoint_failed');}
  try{writeFileSync(fd,JSON.stringify(value));fsyncSync(fd);}finally{closeSync(fd);}
  syncDirectory(directory);
  return new RunCheckpoint(root,path,value);
 }
 static load(root,input){
  const path=location(root,input);
  if(!existsSync(path))throw Error('checkpoint_missing');
  if(statSync(path).size>131072)throw Error('checkpoint_invalid');
  let value;try{value=JSON.parse(readFileSync(path,'utf8'));}catch{throw Error('checkpoint_invalid');}
  if(!validReceipts(value)||value.v!==1)throw Error('checkpoint_invalid');
  if(['project_id','session_id','run_id'].some(key=>value[key]!==input[key]))throw Error('checkpoint_mismatch');
  return new RunCheckpoint(root,path,value);
 }
 static inspect(root,input){return this.load(root,input).summary();}
 static details(root,input){const ledger=this.load(root,input);return {...ledger.summary(),tools:ledger.value.tools.map(tool=>Object.fromEntries(['id','name','input_hash','status','result_hash','result_encoding','session_leaf_id','assistant_leaf_id'].filter(key=>tool[key]!==undefined).map(key=>[key,tool[key]])))};}
 static continuation(root,input){
  if(!validId(input.resume_from)||input.resume_from===input.run_id)throw Error('checkpoint_mismatch');
  const parent=this.load(root,{...input,run_id:input.resume_from}),v=parent.value;
  if(v.status!=='paused'||v.binding_version!==2||v.input_hash!==hash(binding(input)))throw Error('checkpoint_mismatch');
  if(v.continued_by&&v.continued_by!==input.run_id)throw Error('checkpoint_claimed');
  if(v.model_requests!==v.model_responses||v.tools.some(tool=>tool.status==='registered'))throw Error('checkpoint_unresolved');
  const sessionDir=resolve(root,input.project_id,'sessions',input.session_id),file=resolve(root,v.session_file||'.');
  if(!v.leaf_id||!file.startsWith(sessionDir+'/')||!file.endsWith('.jsonl')||!existsSync(file))throw Error('checkpoint_missing');
  return {parent,file,leaf:v.leaf_id};
 }
 claim(child){
  if(this.value.continued_by&&this.value.continued_by!==child)throw Error('checkpoint_claimed');
  this.value.continued_by=child;this.save();
 }
 constructor(root,path,value){this.root=root;this.path=path;this.value=value;this.broken=false;}
 save(){
  if(this.broken)throw Error('checkpoint_failed');
  this.value.updated=new Date().toISOString();
  const directory=join(this.root,this.value.project_id,'checkpoints'),temporary=this.path+'.'+randomUUID()+'.tmp';
  let fd;
  try{fd=openSync(temporary,'wx',0o600);writeFileSync(fd,JSON.stringify(this.value));fsyncSync(fd);closeSync(fd);fd=undefined;renameSync(temporary,this.path);syncDirectory(directory);}
  catch{this.broken=true;throw Error('checkpoint_failed');}
  finally{if(fd!==undefined)closeSync(fd);try{unlinkSync(temporary);}catch{}}
 }
 modelRequest(){
  if(this.broken)throw Error('checkpoint_failed');
  if(this.value.model_requests>=20)throw Error('turn_limit');
  this.value.model_requests++;this.save();
 }
 modelResponse(usage){
  this.value.model_responses++;
  if(usage&&Number.isFinite(usage.totalTokens)&&usage.totalTokens>0){
   this.value.known_usage_responses++;
   for(const key of ['input','output','cacheRead','cacheWrite','totalTokens'])if(Number.isFinite(usage[key])&&usage[key]>0)this.value.usage[key]+=usage[key];
  }
  this.save();
 }
 toolRequest(id,name,args,branch={}){
  if(this.value.tools.some(tool=>tool.id===id))throw Error('tool_call_conflict');
  if(this.value.tools.length>=50)throw Error('tool_limit');
  if(typeof id!=='string'||id.length<1||id.length>200||!['project_query','propose_changes','propose_image','propose_style_tests'].includes(name))throw Error('invalid_request');
  const metadata={};
  for(const key of ['session_leaf_id','assistant_leaf_id'])if(branch[key]!==undefined){if(typeof branch[key]!=='string'||branch[key].length<1||branch[key].length>200)throw Error('invalid_request');metadata[key]=branch[key];}
  this.value.tools.push({id,name,input_hash:hash(args),status:'registered',...metadata});this.save();
 }
 toolResult(id,error,receipt){
  const tool=this.value.tools.find(tool=>tool.id===id);
  if(!tool||tool.status!=='registered')throw Error('tool_call_conflict');
  let result;
  if(!error&&receipt){
   let serialized=receipt.result_json;
   if(serialized!==undefined){
    try{if(typeof serialized!=='string'||serialized.length>2000000||!isDeepStrictEqual(JSON.parse(serialized),receipt.data))throw Error();}catch{throw Error('tool_receipt_invalid');}
   }else serialized=JSON.stringify(receipt.data);
   if(typeof serialized!=='string')throw Error('tool_receipt_invalid');
   result={result_hash:createHash('sha256').update(serialized).digest('hex'),result_encoding:receipt.result_json===undefined?'local_json':'host_json'};
  }
  Object.assign(tool,result);tool.status=error?'rejected':'received';this.save();
 }
 bindSession(manager){
  const file=manager.getSessionFile();
  if(this.value.session_file===null)this.value.start_leaf_id=manager.getLeafId();
  this.value.session_file=file?relative(this.root,file):null;this.value.leaf_id=manager.getLeafId();this.save();
 }
 finish(status,reason=null){this.value.status=status;this.value.reason=reason;this.save();return this.summary();}
 summary(){
  const v=this.value;
  return {v:1,run_id:v.run_id,session_id:v.session_id,status:v.status,reason:v.reason,parent_run_id:v.parent_run_id||null,continued_by:v.continued_by||null,unreturned_models:v.model_requests-v.model_responses,input_hash:v.input_hash,model_requests:v.model_requests,model_limit:20,tool_calls:v.tools.length,tool_limit:50,unresolved_tools:v.tools.filter(tool=>tool.status==='registered').length,unknown_usage_requests:v.model_requests-v.known_usage_responses,usage:v.known_usage_responses?{...v.usage}:null,usage_complete:v.known_usage_responses===v.model_requests,session_saved:Boolean(v.session_file&&v.leaf_id),updated:v.updated};
 }
}
