import {ToolReceiptRecovery,needsToolReceiptRecovery} from './ToolReceiptRecovery';
import {AgentStyleTest} from './AgentStyleTest';
import {PauseToCheckpoint} from './PauseToCheckpoint';
import { useEffect, useRef, useState } from 'react';
import { api, ApiError, base, json, type RecordItem } from './api';
import { ErrorNote, Busy } from './ui';
import { Select } from './Select';
import './agent.css';
import {ProjectPreferenceSettings} from './ProjectPreferences';
import {AgentImagePlan} from './AgentImagePlan';
import {AgentProposal,type ProposalSummary} from './AgentProposal';

export type Ref = { id:string; version:number };
type Run = {style_tests?:{id:string;title:string;source:string}[];pause_requested?:boolean;preferences?:{revision:number;text:string}|null;checkpoint?:{reason?:string;model_requests:number;model_limit:number;tool_calls:number;tool_limit:number;unresolved_tools:number;unreturned_models:number;session_saved:boolean};continuation?:{parent_run_id?:string;child_run_id?:string;known_tokens:number;unknown_runs:number}; image_plans?:ProposalSummary[];proposals?:ProposalSummary[];skills?:{hash:string;name:string;version:string;resource_only?:boolean}[];id:string; message:string; reply:string; status:string; error?:string; usage?:{totalTokens?:number|null}; events?:{seq:number;event:string;delta?:string}[] };
type Session = { message_count?:number;id:string; stage:string; version:number; refs:Ref[]; runs?:Run[] };
export type AgentStage = 'setup'|'memory'|'skeleton'|'outline'|'style'|'asset'|'script'|'package';
const names:Record<AgentStage,string>={setup:'系统配置',memory:'理解与记忆',skeleton:'改编骨架',outline:'分集细纲',style:'画风',asset:'资产',script:'脚本审核',package:'逐格生图包'};
const statusName:Record<string,string>={queued:'等待回复',running:'正在回复',completed:'回复完成',failed:'回复失败',cancelled:'已取消',interrupted:'已中断',paused:'额度暂停，等待明确处理',continued:'已明确续接，原记录保留'};
const errorName:Record<string,string>={provider_error:'模型请求失败，请检查服务地址、模型和凭据。',runtime_error:'AI 运行失败，请检查配置后重试。',cancelled:'本次回复已取消。',turn_limit:'已达到单次模型轮次上限，请检查当前结果。',tool_limit:'已达到单次工具额度，请检查当前结果。',session_busy:'此会话仍在处理回复，请稍后刷新。',checkpoint_missing:'原检查点或会话文件缺失，未提交模型；请核对完整备份。',checkpoint_mismatch:'固定输入或会话分支不匹配，未提交模型。',checkpoint_claimed:'此检查点已被续接，请重新打开会话核对后续记录。',checkpoint_unresolved:'检查点仍有未决回执，不能重放旧调用。',checkpoint_failed:'调用检查点保存失败，已停止后续派发，请核对存储。',run_recorded:'此运行编号已有调用登记，未重复请求模型。'};
const drafts=new Map<string,string>();
const active=(run:Run)=>['queued','running'].includes(run.status);

export type PlanReply={id:string;reply:string;refs:Ref[]};
export function AgentPanel({pid,stage,records,onConfigure,onChanged,boundRefs,onUseReply}:{pid:string;stage:AgentStage;records:RecordItem[];onConfigure?:()=>void;onChanged?:()=>void|Promise<void>;boundRefs?:Ref[];onUseReply?:(reply:PlanReply)=>void}) {
  const [sessions,setSessions]=useState<Session[]>([]),[session,setSession]=useState<Session|null>(null),[runs,setRuns]=useState<Run[]>([]);
  const scope=boundRefs?JSON.stringify([...boundRefs].sort((a,b)=>a.id.localeCompare(b.id))):'';
  const draftKey=(sid='new')=>`${pid}/${stage}/${scope?scope+'/':''}${sid}`;
  const [refs,setRefs]=useState<Ref[]>(boundRefs||[]),[message,setMessage]=useState(()=>drafts.get(draftKey())||''),[error,setError]=useState(''),[loading,setLoading]=useState(true),[sending,setSending]=useState(false),[health,setHealth]=useState(''),[refQuery,setRefQuery]=useState(''),[refPage,setRefPage]=useState(0);
  const mounted=useRef(true),loadingSession=useRef(0);
  const endpoint=base(pid)+'/agent';
  const pending=runs.find(active),paused=runs.find(r=>r.status==='paused');
  const [continuing,setContinuing]=useState(''),[confirmed,setConfirmed]=useState(''),[continuationError,setContinuationError]=useState<{id:string;message:string}|null>(null);
  const candidates=records.filter(r=>r.kind===stage || (stage==='memory' && r.kind==='original'));
  const filtered=candidates.filter(r=>!refQuery||`${r.title} 第${r.content.episode||''}话 第${r.content.panel||''}格`.includes(refQuery));
  const pageSize=50;
  async function loadSession(sid:string) {
    const ticket=++loadingSession.current;
    const value=await api<Session>(endpoint+'/sessions/'+sid);
    if(!mounted.current || ticket!==loadingSession.current)return;
    setMessage(drafts.get(draftKey(value.id))||'');setSession(value);setSessions(prev=>prev.map(s=>s.id===value.id?value:s));setRefs(value.refs);setRuns(value.runs||[]);
  }
  useEffect(()=>{
    mounted.current=true;
    Promise.all([api<Session[]>(endpoint+'/sessions?stage='+stage+(boundRefs?'&refs='+encodeURIComponent(JSON.stringify(boundRefs)):'')),api<{status:string}>('/agent/health')]).then(async ([list,state])=>{
      if(!mounted.current)return;
      setSessions(list);setHealth(state.status);
      if(list[0]&&!drafts.get(draftKey()))await loadSession(list[0].id);
    }).catch(e=>{if(mounted.current)setError(e.message);}).finally(()=>{if(mounted.current)setLoading(false);});
    return ()=>{mounted.current=false;++loadingSession.current;};
  },[endpoint,stage]);
  useEffect(()=>{
    if(!pending)return;
    let disposed=false,timer:ReturnType<typeof setTimeout>,cursor=0,text='';
    async function poll(){
      try{
        const value=await api<Run>(endpoint+'/runs/'+pending!.id+'?after='+cursor);
        if(disposed)return;
        for(const event of value.events||[]){cursor=event.seq;if(event.event==='text_delta')text+=event.delta||'';}
        setRuns(prev=>prev.map(r=>r.id===value.id?{...value,reply:active(value)?text:value.reply}:r));
        if(active(value))timer=setTimeout(poll,700);
      }catch(e){if(!disposed){setError((e as Error).message);timer=setTimeout(poll,2000);}}
    }
    void poll();return ()=>{disposed=true;clearTimeout(timer);};
  },[pending?.id,endpoint]);
  async function send(){
    if(!message.trim()||sending||pending||paused||continuing)return;
    const text=message;setSending(true);setError('');
    try{
      let current=session;
      if(!current){
        current=await api<Session>(endpoint+'/sessions',json('POST',{stage,refs}));
        if(!mounted.current)return;
        drafts.delete(draftKey());drafts.set(draftKey(current.id),text);
        setSession(current);setSessions(prev=>[current!,...prev]);
      }
      const result=await api<Run>(endpoint+'/sessions/'+current.id+'/messages',json('POST',{message:text,expected_version:current.version}));
      if(!mounted.current)return;
      setRuns(prev=>[...prev,result]);setSession({...current,version:current.version+1,message_count:(current.message_count??current.version)+1});setSessions(prev=>prev.map(s=>s.id===current!.id?{...s,version:current!.version+1,message_count:(current!.message_count??current!.version)+1}:s));drafts.delete(draftKey(current.id));setMessage('');
    }catch(e){if(mounted.current){setError((e as Error).message);if(e instanceof ApiError&&e.status===409)try{await onChanged?.();}catch{}}}finally{if(mounted.current)setSending(false);}
  }
  async function cancel(){
    if(!pending)return;
    try{const value=await api<Run>(endpoint+'/runs/'+pending.id+'/cancel',json('POST',{}));if(mounted.current)setRuns(prev=>prev.map(r=>r.id===value.id?value:r));}
    catch(e){if(mounted.current)setError((e as Error).message);}
  }
  async function continueRun(run:Run){
    if(!session||continuing||confirmed!==run.id)return;
    setContinuing(run.id);setContinuationError(null);
    try{
      await api<Run>(endpoint+'/runs/'+run.id+'/continue',json('POST',{expected_version:session.version,confirm:true}));
      if(mounted.current){setConfirmed('');await loadSession(session.id);}
    }catch(e){if(mounted.current){setContinuationError({id:run.id,message:(e as Error).message});if(e instanceof ApiError&&e.status===409)try{await onChanged?.();}catch{}}}
    finally{if(mounted.current)setContinuing('');}
  }
  async function endPause(run:Run){
    if(continuing)return;setContinuing(run.id);setContinuationError(null);
    try{
      const value=await api<Run>(endpoint+'/runs/'+run.id+'/cancel',json('POST',{}));
      if(mounted.current){setRuns(prev=>prev.map(r=>r.id===value.id?value:r));setConfirmed('');try{await onChanged?.();}catch{}}
    }catch(e){if(mounted.current)setContinuationError({id:run.id,message:(e as Error).message});}
    finally{if(mounted.current)setContinuing('');}
  }
  const stale=session?.refs.some(ref=>records.find(r=>r.id===ref.id)?.version!==ref.version);
  return <section className="agent-panel" aria-label={names[stage]+' AI 助手'}>
    {onConfigure&&<div className="actions"><button onClick={onConfigure}>配置本项目流程</button></div>}
    <p className="agent-scope">可查询本项目原著与固定版本资料，也可提出修改候选。只有核对后点击采用才写入新版本，讨论不会自动修改成品或触发生图。</p>
    {stage!=='setup'&&<ProjectPreferenceSettings pid={pid} title="本项目创作偏好"/>}
    {stage==='script'&&<p className="notice">脚本可查询、修改、新增或删除。先附加当前脚本；新增需指定未用格号，不重排旧格；删除采用后会撤下该格关联的生图包、图片和试制确认，历史保留。</p>}
    {(stage==='style'||stage==='asset')&&<p className="notice">可给出提示词，也可提出新建或重生成方案。重生成请先附加目标；核对方案后创建预览，再明确确认生图。助手尚不能读取图片像素，视觉结论仍待实图验证。</p>}
    {loading?<Busy/>:<>
      {health!=='ready'&&<p className="notice" role="status">Pi 运行层当前不可用。请检查 Node 和运行依赖；人工编辑仍可使用。</p>}
      <div className="agent-session-bar">
        <label>会话<Select aria-label="AI 会话" value={session?.id||''} disabled={sending||!!continuing} onChange={e=>{
          setError('');if(!e.target.value){++loadingSession.current;setSession(null);setRuns([]);setRefs(boundRefs||[]);setMessage(drafts.get(draftKey())||'');}else void loadSession(e.target.value).catch(e=>setError(e.message));
        }}><option value="">新建讨论</option>{sessions.map((s,i)=><option value={s.id} key={s.id}>{names[stage]} · 讨论 {sessions.length-i} · {s.version} 条消息</option>)}</Select></label>
      </div>
      <details className="agent-refs"><summary>本次资料 · {refs.length} 项固定版本</summary>
        {(session||boundRefs)?<ul>{refs.map(ref=><li key={ref.id}>{records.find(r=>r.id===ref.id)?.title||ref.id} · v{ref.version}</li>)}{!refs.length&&<li>未附加资料，可通过项目查询工具按需检索。</li>}</ul>:<div className="agent-ref-picker"><label>查找资料<input value={refQuery} onChange={e=>{setRefQuery(e.target.value);setRefPage(0);}} placeholder="按名称、话号或格号查找"/></label>
          <div className="agent-ref-list">{filtered.slice(refPage*pageSize,(refPage+1)*pageSize).map(r=><label key={r.id}><input type="checkbox" checked={refs.some(ref=>ref.id===r.id)} disabled={refs.length>=100&&!refs.some(ref=>ref.id===r.id)} onChange={e=>setRefs(prev=>e.target.checked?[...prev,{id:r.id,version:r.version}]:prev.filter(ref=>ref.id!==r.id))}/><span>{r.title} · v{r.version}{r.content.episode?` · 第${r.content.episode}话${r.content.panel?`第${r.content.panel}格`:''}`:''}</span></label>)}{!filtered.length&&<p>{candidates.length?'没有匹配资料，请修改查找条件。':'当前阶段暂无文档，仍可查询项目已有资料。'}</p>}</div>
          <div className="agent-ref-pages"><small>{filtered.length?`${refPage*pageSize+1}–${Math.min((refPage+1)*pageSize,filtered.length)} / ${filtered.length} 项`:'0 项'} · 最多附加100项，只有附加的本阶段资料可提出编辑候选</small><button type="button" aria-label="上一页资料" disabled={!refPage} onClick={()=>setRefPage(p=>p-1)}>上一页</button><button type="button" aria-label="下一页资料" disabled={(refPage+1)*pageSize>=filtered.length} onClick={()=>setRefPage(p=>p+1)}>下一页</button></div>
        </div>}
      </details>
      {stale&&!boundRefs&&<p className="notice" role="status">资料已有新版本；当前仍引用上述固定版本。<button disabled={sending||!!pending||!!paused||!!continuing} onClick={async()=>{if(!session)return;try{const next=await api<Session>(endpoint+'/sessions/'+session.id+'/refs',json('PUT',{expected_version:session.version,refs:session.refs.map(ref=>{const record=records.find(r=>r.id===ref.id);if(!record)throw Error('目标已不可用，请新建讨论选择资料');return {id:ref.id,version:record.version};})}));setSession(next);setRefs(next.refs);setSessions(prev=>prev.map(s=>s.id===next.id?next:s));setError('');}catch(e){setError((e as Error).message);}}}>更新附加资料到已保存最新版本</button>更新只影响后续运行，保留讨论历史和旧候选。</p>}
      <div className="agent-transcript" aria-label="AI 讨论记录">
        {!runs.length&&<div className="agent-empty"><h3>从当前创作问题开始</h3><p>{stage==='memory'?'例如：主角与某人物为何发生冲突？请给出原著依据。':stage==='package'?'例如：当前镜头的站位提示词有哪些歧义？':`询问${names[stage]}的信息，或说明希望调整的内容。`}</p></div>}
        {runs.map(run=><article key={run.id} id={"agent-run-"+run.id} tabIndex={-1} className="agent-exchange"><div className="agent-user"><strong>你</strong><p>{run.message}</p></div><div className="agent-answer"><strong>AI 助手</strong><p>{run.reply||(active(run)?'正在查阅资料并准备回复…':'本次未取得答复。')}</p><small>{active(run)&&run.pause_requested?'正在暂停，等待收尾':run.status==='paused'&&run.checkpoint?.reason==='tools_recovered'?'结果已补回，原任务已暂停':run.status==='paused'&&run.checkpoint?.reason==='manual_pause'?'已暂停，等待明确处理':statusName[run.status]||run.status}{typeof run.usage?.totalTokens==='number'&&run.usage.totalTokens>0?` · ${run.usage.totalTokens} tokens · 金额未知`:' · 用量未知 · 金额未知'}</small>{!!run.skills?.length&&<p className="agent-run-skills">本次流程：{run.skills.map(s=>`${s.name} v${s.version}${s.resource_only?'（引用资料）':''}`).join("、")}</p>}{run.preferences&&<details className="agent-run-preferences"><summary>本次项目偏好 · v{run.preferences.revision}{!run.preferences.text?' · 未设置':''}</summary><p>{run.preferences.text||'本次未设置创作偏好。历史偏好不自动沿用。'}</p></details>}{onUseReply&&run.status==='completed'&&run.reply.trim()&&<button type="button" onClick={()=>onUseReply({id:run.id,reply:run.reply,refs:session?.refs||refs})}>将此回复加入生成方案</button>}{run.proposals?.map(p=><AgentProposal key={p.id} pid={pid} proposal={p} runStatus={run.status} onChanged={async()=>{await onChanged?.();if(session)await loadSession(session.id);}}/>)}{run.style_tests?.map(p=><AgentStyleTest key={p.id} pid={pid} summary={p} runStatus={run.status} records={records} onChanged={async()=>{await onChanged?.();if(session)await loadSession(session.id);}}/>)}{run.image_plans?.map(p=><AgentImagePlan key={p.id} pid={pid} summary={p} runStatus={run.status} records={records} onChanged={async()=>{await onChanged?.();if(session)await loadSession(session.id);}}/>)}{run.continuation?.parent_run_id&&<p className="agent-run-skills">明确续接原任务；续接链已知{run.continuation.known_tokens} tokens · {run.continuation.unknown_runs}段用量未知 · 金额未知。原输出与候选保留，不自动采用。</p>}
          {needsToolReceiptRecovery(run.status,run.checkpoint)&&session&&<ToolReceiptRecovery key={run.id} endpoint={endpoint+'/runs/'+run.id} cancelEndpoint={endpoint+'/runs/'+run.id+'/cancel'} expectedVersion={session.version} focusId={'agent-checkpoint-'+run.id} onChanged={async()=>{setConfirmed('');await loadSession(session.id);}}/>}
          {run.status==='paused'&&<div className="agent-checkpoint" id={'agent-checkpoint-'+run.id} tabIndex={-1}>
            <h4>{run.checkpoint?.reason==='tools_recovered'?'结果已补回，原任务已暂停；请明确续接或结束':run.checkpoint?.reason==='manual_pause'?'已按请求暂停，检查点已保留':'检查点已保留'}</h4>
            {run.checkpoint&&<p>本段模型登记 {run.checkpoint.model_requests}/{run.checkpoint.model_limit}（含压缩） · 工具派发 {run.checkpoint.tool_calls}/{run.checkpoint.tool_limit}</p>}
            <p>续接沿用原任务、固定输入与权限，另开一段明确授权的额度；旧调用不会自动重放，候选仍需核对采用。新意见请在结束暂停后另行发送。</p>
            {run.checkpoint?.session_saved&&!run.checkpoint.unresolved_tools&&!run.checkpoint.unreturned_models?<>
              <label className="agent-continue-confirm"><input type="checkbox" checked={confirmed===run.id} disabled={!!continuing} onChange={e=>setConfirmed(e.target.checked?run.id:'')}/>已核对原固定输入，授权新增最多20次模型请求和50次工具派发；费用未知。</label>
              <div className="actions"><button type="button" className="primary" disabled={!!continuing||confirmed!==run.id||!!pending||health!=='ready'} onClick={()=>void continueRun(run)}>{continuing===run.id?'正在处理…':'明确续接此检查点'}</button><button type="button" disabled={!!continuing} onClick={()=>void endPause(run)}>结束这次暂停</button></div>
            </>:<><p>检查点缺少会话或仍有未决调用，不能自动恢复或重发；请先核对原回执。</p><button type="button" disabled={!!continuing} onClick={()=>void endPause(run)}>结束这次暂停</button></>}
            {continuationError?.id===run.id&&<ErrorNote message={continuationError.message}/>}
          </div>}
          {run.error&&!['paused','continued'].includes(run.status)&&!(run.status==='cancelled'&&['turn_limit','tool_limit'].includes(run.error))&&<ErrorNote message={errorName[run.error]||run.error}/>}</div></article>)}
      </div>
      <form className="agent-composer" onSubmit={e=>{e.preventDefault();void send();}}>
        <label htmlFor="agent-message">发送给 AI 的消息</label><small className="agent-draft-note">未发送草稿在本次应用内保留；刷新或退出前请发送或复制。</small>
        <textarea id="agent-message" value={message} maxLength={20000} placeholder="写下问题或修改要求…" rows={4} onChange={e=>{setMessage(e.target.value);drafts.set(draftKey(session?.id),e.target.value);}}/>
        <ErrorNote message={error}/>
        {pending&&<PauseToCheckpoint key={pending.id} endpoint={endpoint+'/runs/'+pending.id+'/pause'} requested={!!pending.pause_requested} focusId={'agent-checkpoint-'+pending.id} fallbackId={'agent-run-'+pending.id} onChanged={async()=>{if(session)await loadSession(session.id);}}/>}
        <div className="agent-compose-actions"><small>使用已配置的文本模型。密钥请在模型设置中管理。</small>{pending?<button type="button" onClick={()=>void cancel()}>取消回复</button>:<button className="primary" disabled={sending||!!continuing||!!paused||health!=='ready'||!message.trim()}>{sending?'正在发送…':'发送消息'}</button>}</div>
      </form>
    </>}
  </section>;
}
