import { createInterface } from 'node:readline';
import { mkdir } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { createAgentSession, DefaultResourceLoader, SettingsManager, SessionManager } from '@earendil-works/pi-coding-agent';
import { createModelRuntime } from './model.mjs';
import { ProjectBridge } from './tools.mjs';
import { RunCheckpoint } from './checkpoints.mjs';
import {recoverTools} from './tool-recovery.mjs';
import {isDeepStrictEqual} from 'node:util';

const active = new Map();
const busy = new Set();
const cancelledRuns = new Map();
const root = resolve(process.env.COMIC_AGENT_DATA || './data/agent');
const emit = value => process.stdout.write(JSON.stringify({ v: 1, ...value }) + '\n');
const ids = m => ({ request_id: m.request_id, run_id: m.run_id, session_id: m.session_id });
const fail = (m, code, data) => emit({ ...ids(m), type: 'error', error: { code }, ...(data?{data}:{}) });
const validId = value => typeof value === 'string' && /^[a-zA-Z0-9_-]{1,100}$/.test(value);

async function run(m) {
  if (cancelledRuns.has(m.run_id)) return fail(m, 'cancelled');
  if (!m.config?.model || !m.config?.url || !m.secret) return fail(m, 'configuration_missing');
  if (![m.project_id, m.session_id, m.run_id].every(validId) || typeof m.prompt !== 'string' || m.prompt.length > 200000) return fail(m, 'invalid_request');
  if (!['openai-completions', 'openai-responses', 'anthropic-messages'].includes(m.config.api || 'openai-completions')) return fail(m, 'unsupported_api');
  const setup = m.type === 'setup';
  if(m.start_paused!==undefined&&(setup||typeof m.start_paused!=='boolean'))return fail(m,'invalid_request');
  const allowedTools = setup ? ['setup_catalog'] : m.tools === true ? ['project_query','propose_changes'] : Array.isArray(m.tools) ? m.tools : [];
  if (allowedTools.some(name => !(setup ? ['setup_catalog'] : ['project_query','propose_changes','propose_image','propose_style_tests']).includes(name))) return fail(m,'tool_denied');
  const key = `${m.project_id}/${m.session_id}`;
  if (busy.has(key) || active.has(m.run_id)) return fail(m, 'session_busy');
  busy.add(key);
  const state = { session: null, cancelled: false, pausable:!setup,pauseRequested:m.start_paused===true, bridge: new ProjectBridge(ids(m),emit,()=>{state.limited='tool_limit';void state.session?.abort();},setup ? 8 : 50,{
    beforeDispatch:(id,name,args)=>{if(state.pauseRequested){state.limited='manual_pause';throw Error('manual_pause');}try{const branch={};
      if(state.manager){const leaf=state.manager.getLeafId();if(leaf)branch.session_leaf_id=leaf;
       const entry=state.manager.getBranch().find(e=>e.type==='message'&&e.message===state.assistant&&e.message.content?.some(c=>c.type==='toolCall'&&c.id===id&&c.name===name&&isDeepStrictEqual(c.arguments,args)));
       if(entry)branch.assistant_leaf_id=entry.id;
      }
      state.checkpoint?.toolRequest(id,name,args,branch);}catch(e){state.limited=e.message==='tool_limit'?'tool_limit':'checkpoint_failed';void state.session?.abort();throw e;}},
    afterReceipt:(id,error,receipt)=>{try{state.checkpoint?.toolResult(id,error,receipt);}catch(e){state.limited='checkpoint_failed';void state.session?.abort();throw e;}},
  }), limited: false,checkpoint:null,manager:null };
  active.set(m.run_id, state);
  const terminal=(code,data={})=>{
    if(state.checkpoint){
      try{if(state.manager)state.checkpoint.bindSession(state.manager);data.checkpoint=state.checkpoint.finish(code==='turn_limit'||code==='tool_limit'||code==='manual_pause'?'paused':code==='cancelled'?'cancelled':code?'failed':'completed',code||null);if(code)data.usage=data.checkpoint.usage_complete?data.checkpoint.usage:null;}
      catch{return fail(m,'checkpoint_failed');}
    }
    if(code)return fail(m,code,data);
    emit({...ids(m),type:'result',data});
  };
  try {
    if(setup&&m.resume_from)return fail(m,'checkpoint_mismatch');
    const continuation=m.resume_from?RunCheckpoint.continuation(root,m):null;
    const cwd = join(root, m.project_id);
    const agentDir = join(cwd, 'config');
    await mkdir(agentDir, { recursive: true, mode: 0o700 });
    const settingsManager = SettingsManager.inMemory({ compaction: { enabled: !setup }, retry: { enabled: false } });
    const loader = new DefaultResourceLoader({ cwd, agentDir, settingsManager, noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true, systemPrompt: m.system || '你是条漫工作台助手。仅依据提供的项目证据回答，不虚构执行、审核或生成结果。' });
    await loader.reload();
    let modelRequests=0;
    const modelRuntime = await createModelRuntime(m.config, m.secret,{
      beforeRequest:()=>{
        if(state.cancelled)throw Error('cancelled');
        if(state.pauseRequested){state.limited='manual_pause';throw Error('manual_pause');}
        try{if(state.checkpoint)state.checkpoint.modelRequest();else if(modelRequests>=8)throw Error('turn_limit');modelRequests++;}
        catch(e){state.limited=e.message==='turn_limit'?'turn_limit':'checkpoint_failed';throw e;}
      },
      afterResponse:usage=>{try{state.checkpoint?.modelResponse(usage);}catch(e){state.limited='checkpoint_failed';throw e;}},
    });
    // Credentials never enter prompt, session metadata or protocol events.
    m.secret = undefined;
    const sessionManager = setup ? SessionManager.inMemory(cwd) : continuation?SessionManager.open(continuation.file,join(cwd,'sessions',m.session_id),cwd):SessionManager.continueRecent(cwd, join(cwd, 'sessions', m.session_id));
    if(continuation){
      if(!sessionManager.getEntry(continuation.leaf))throw Error('checkpoint_mismatch');
      sessionManager.branch(continuation.leaf);
      continuation.parent.claim(m.run_id);
    }
    if(!setup)state.checkpoint=RunCheckpoint.start(root,m);
    const taskPrompt=continuation?'本次由用户明确授权从固定检查点续接，新增最多20次模型请求（含压缩）/50次宿主工具派发。不要重放旧工具；历史未执行/中止工具不是已完成。仅按以下原任务、原固定资料和原权限继续；候选仍须用户采用。\n'+m.prompt:m.prompt;
    const stream=modelRuntime.streamSimple.bind(modelRuntime);
    modelRuntime.streamSimple=(model,context,options)=>{
      const hasTask=context.messages.some(message=>message.role==='user'&&(typeof message.content==='string'?message.content:message.content.filter(block=>block.type==='text').map(block=>block.text).join(''))===taskPrompt);
      // SDK overflow recovery may replace the current task with a lossy summary.
      if(!setup&&options?.sessionId===sessionManager.getSessionId()&&!hasTask){
        context={...context,messages:[...context.messages,{role:'user',content:'宿主重新提供本次原始任务与固定资料。摘要仅是笔记，不得替换以下范围、版本或授权；历史工具不因此重放。\n'+taskPrompt,timestamp:Date.now()}]};
      }
      return stream(model,context,options);
    };
    const { session } = await createAgentSession({ cwd, agentDir, modelRuntime, model: modelRuntime.getModel('workbench', m.config.model), settingsManager, resourceLoader: loader, sessionManager, tools: allowedTools, customTools: state.bridge.tools().filter(tool => allowedTools.includes(tool.name)) });
    state.session = session;state.manager=sessionManager;
    if(state.checkpoint)state.checkpoint.bindSession(sessionManager);
    if (state.cancelled) return terminal('cancelled');
    let answer = '', usage=null, usageComplete=true;
    session.subscribe(event => {
      if (event.type === 'message_update' && event.assistantMessageEvent?.type === 'text_delta') {
        const delta = event.assistantMessageEvent.delta;
        answer += delta;
        emit({ ...ids(m), type: 'event', event: 'text_delta', delta });
      }
      if (event.type === 'message_end' && event.message?.role === 'assistant') {
        state.assistant=event.message;
        const u=event.message.usage;
        if(!u || !(u.totalTokens>0)) usageComplete=false;
        else {
          usage ||= {input:0,output:0,cacheRead:0,cacheWrite:0,totalTokens:0,cost:null};
          for(const key of ['input','output','cacheRead','cacheWrite','totalTokens']) usage[key]+=u[key]||0;
        }
      }
    });
    await session.prompt(taskPrompt);
    if (state.cancelled) return terminal('cancelled');
    if (state.limited) return terminal(state.limited);
    const last = session.messages.filter(v => v.role === 'assistant').at(-1);
    if (last?.stopReason === 'error' || last?.stopReason === 'aborted') return terminal('provider_error');
    const totals=state.checkpoint?.summary();
    terminal(null,{text:m.final_only?(last?.content||[]).filter(v=>v.type==='text').map(v=>v.text).join(''):answer,usage:totals?(totals.usage_complete?totals.usage:null):(usageComplete?usage:null)});
  } catch (error) {
    // Provider error bodies may contain credentials; expose only bounded error codes.
    terminal(state.limited || (state.cancelled ? 'cancelled' : ['run_recorded','checkpoint_failed','checkpoint_missing','checkpoint_mismatch','checkpoint_claimed','checkpoint_unresolved'].includes(error.message)?error.message:'runtime_error'));
  } finally {
    state.bridge.close();
    state.session?.dispose();
    active.delete(m.run_id);
    busy.delete(key);
    m.secret = undefined;
  }
}

function validImages(images) {
  if (images === undefined) return true;
  if (!Array.isArray(images) || images.length > 8) return false;
  let total = 0;
  return images.every(image => {
    if (!image || typeof image !== 'object' || Object.keys(image).sort().join(',') !== 'data,mimeType' || typeof image.data !== 'string' || image.data.length > 5592408 || !/^[A-Za-z0-9+/]+={0,2}$/.test(image.data)) return false;
    const bytes = Buffer.from(image.data, 'base64');
    total += bytes.length;
    if (!bytes.length || bytes.length > 4 * 1024 * 1024 || total > 6 * 1024 * 1024 || bytes.toString('base64') !== image.data) return false;
    if (image.mimeType === 'image/png') return bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]));
    if (image.mimeType === 'image/jpeg') return bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255;
    return image.mimeType === 'image/webp' && bytes.subarray(0,4).toString() === 'RIFF' && bytes.subarray(8,12).toString() === 'WEBP';
  });
}

// Constrained calls have no tools, session history, filesystem or global resources.
async function complete(m) {
  if (!validImages(m.images)) return fail(m, 'invalid_request');
  if (cancelledRuns.has(m.run_id)) return fail(m, 'cancelled');
  if (!m.config?.model || !m.config?.url || typeof m.secret !== 'string' || !m.secret) return fail(m, 'configuration_missing');
  if (!validId(m.run_id) || typeof m.prompt !== 'string' || m.prompt.length > 200000 || (m.system != null && (typeof m.system !== 'string' || m.system.length > 200000))) return fail(m, 'invalid_request');
  if (!['openai-completions', 'openai-responses', 'anthropic-messages'].includes(m.config.api || 'openai-completions')) return fail(m, 'unsupported_api');
  if (active.has(m.run_id)) return fail(m, 'session_busy');
  const controller = new AbortController();
  const state = {cancelled: false, session: {abort: () => controller.abort(), dispose: () => controller.abort()}, bridge: {close() {}}};
  active.set(m.run_id, state);
  try {
    const runtime = await createModelRuntime(m.config, m.secret, {vision: Boolean(m.images?.length)});
    m.secret = undefined;
    const message = await runtime.completeSimple(runtime.getModel('workbench', m.config.model), {
      systemPrompt: m.system || '', messages: [{role: 'user', content: m.images?.length ? [{type:'text',text:m.prompt}, ...m.images.map(image => ({type:'image',...image}))] : m.prompt, timestamp: Date.now()}],
    }, {temperature: 0, maxTokens: 8192, signal: controller.signal});
    if (state.cancelled) return fail(m, 'cancelled');
    if (message.stopReason === 'error' || message.stopReason === 'aborted') return fail(m, 'provider_error');
    const text = message.content.filter(v => v.type === 'text').map(v => v.text).join('');
    const usage = message.usage?.totalTokens > 0 ? {...message.usage, cost: null} : null;
    emit({...ids(m), type: 'result', data: {text, usage}});
  } catch {
    fail(m, state.cancelled ? 'cancelled' : 'runtime_error');
  } finally {
    active.delete(m.run_id);
    m.secret = undefined;
  }
}

async function dispatch(m) {
  if (m.v !== 1) return fail(m, 'protocol_mismatch');
  if (m.type === 'health') return emit({ ...ids(m), type: 'result', data: { sdk: '1.5.0', protocol: 1, tools: [] } });
  if (m.type === 'checkpoint' || m.type === 'checkpoint_details') {
    try{const checkpoint=m.type==='checkpoint_details'?RunCheckpoint.details(root,m):RunCheckpoint.inspect(root,m);return emit({...ids(m),type:'result',data:{checkpoint,interrupted:checkpoint.status==='running'&&!active.has(m.run_id)}});}
    catch(error){return fail(m,['invalid_request','checkpoint_missing','checkpoint_mismatch','checkpoint_invalid'].includes(error.message)?error.message:'checkpoint_failed');}
  }
  if(m.type==='recover_tools'){
    if(![m.project_id,m.session_id,m.run_id,m.recovery_id].every(validId))return fail(m,'invalid_request');
    const key=`${m.project_id}/${m.session_id}`;
    if(active.has(m.run_id)||busy.has(key))return fail(m,'session_busy');
    if(cancelledRuns.has(m.run_id))return fail(m,'recovery_conflict');
    busy.add(key);
    try{return emit({...ids(m),type:'result',data:recoverTools(root,m)});}
    catch(error){return fail(m,['recovery_conflict','recovery_failed'].includes(error.message)?error.message:'recovery_failed');}
    finally{busy.delete(key);}
  }
  if (m.type === 'run' || m.type === 'setup') return run(m);
  if (m.type === 'complete') return complete(m);
  if (m.type === 'tool_result') { active.get(m.run_id)?.bridge.accept(m); return; }
  if(m.type==='pause'){
    if(!validId(m.run_id))return fail(m,'invalid_request');
    const state=active.get(m.run_id);
    if(state&&!state.pausable)return fail(m,'pause_not_supported');
    if(state)state.pauseRequested=true;
    return emit({...ids(m),type:'result',data:{pause_requested:Boolean(state),active:Boolean(state)}});
  }
  if (m.type === 'cancel') {
    if (validId(m.run_id)) {
      cancelledRuns.set(m.run_id, Date.now());
      for (const [id,time] of cancelledRuns) { if (cancelledRuns.size > 1000 || Date.now()-time > 3600000) cancelledRuns.delete(id); else break; }
    }
    const state = active.get(m.run_id);
    if (state) { state.cancelled = true; state.bridge.close(); await state.session?.abort(); }
    return emit({ ...ids(m), type: 'result', data: { cancelled: Boolean(state) } });
  }
  if (m.type === 'shutdown') {
    for (const state of active.values()) { state.cancelled = true; state.bridge.close(); await state.session?.abort(); state.session?.dispose(); }
    emit({ ...ids(m), type: 'result', data: { stopped: true } });
    process.exit(0);
  }
  fail(m, 'unknown_command');
}
const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
lines.on('line', line => {
  if (line.length > 9000000) return fail({}, 'request_too_large');
  let m;
  try { m = JSON.parse(line); } catch { return fail({}, 'invalid_json'); }
  if (!m || typeof m !== 'object') return fail({}, 'invalid_request');
  void dispatch(m).catch(() => fail(m, 'runtime_error'));
});
lines.on('close', () => { for (const state of active.values()) state.session?.dispose(); process.exit(0); });
