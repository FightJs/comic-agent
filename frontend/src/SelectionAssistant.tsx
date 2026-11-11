import {ToolReceiptRecovery,needsToolReceiptRecovery} from './ToolReceiptRecovery';
import {PauseToCheckpoint} from './PauseToCheckpoint';
import {useEffect,useRef,useState} from 'react';
import {api,base,json,type RecordItem} from './api';
import {Badge,Drawer,ErrorNote} from './ui';
import type {TextSelection} from './textSelection';
import './agent-proposals.css';
type Session={id:string;version:number;refs:{id:string;version:number}[];selection:TextSelection;runs:Run[]};
const statusName:Record<string,string>={queued:'等待回复',running:'正在回复',completed:'回复已完成',paused:'额度暂停',continued:'已续接',cancelled:'已取消',interrupted:'已中断',failed:'回复失败'};
type Run={pause_requested?:boolean;checkpoint?:{reason?:string;session_saved:boolean;unreturned_models:number;unresolved_tools:number;model_requests:number;tool_calls:number};events?:{seq:number;event:string;delta?:string}[];tool_calls?:number;usage?:{totalTokens:number}|null;id:string;status:string;message:string;reply:string;error:string;proposals:{id:string;title:string;status:string;source:string}[]};
type Proposal={id:string;title:string;status:string;source:string;changes:{version:number;selection:TextSelection;patch:{text:string}}[]};
export function SelectionAssistant({record,selection,onClose,onApply}:{record:RecordItem;selection:TextSelection|null;onClose:()=>void;onApply:(proposal:Proposal)=>Promise<void>}){
 const [session,setSession]=useState<Session|null>(null),[history,setHistory]=useState<Session[]>([]),[message,setMessage]=useState(''),[detail,setDetail]=useState<Proposal|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[confirmed,setConfirmed]=useState('');
 const alive=useRef(true),area=useRef<HTMLDivElement>(null);const root=base(record.project_id)+'/agent';
 const pending=session?.runs?.find(r=>['queued','running'].includes(r.status));
 const active=!!pending;
 const paused=session?.runs?.some(r=>r.status==='paused');
 async function load(id:string){const value=await api<Session>(root+'/sessions/'+id);if(alive.current)setSession(value);}
 useEffect(()=>{alive.current=true;api<Session[]>(root+'/sessions?stage='+record.kind+'&selection=true').then(values=>{if(alive.current)setHistory(values.filter(s=>s.refs[0]?.id===record.id));}).catch(e=>{if(alive.current)setError(e.message);});return()=>{alive.current=false;};},[]);
 useEffect(()=>{
  if(!pending||!session)return;
  const id=pending.id,sid=session.id;let disposed=false,cursor=0,text='',timer:ReturnType<typeof setTimeout>;
  async function poll(){
   try{
    const value=await api<Run>(root+'/runs/'+id+'?after='+cursor);
    if(disposed)return;
    for(const event of value.events||[]){cursor=event.seq;if(event.event==='text_delta')text+=event.delta||'';}
    const running=['queued','running'].includes(value.status);
    setSession(previous=>previous?.id===sid?{...previous,runs:previous.runs.map(r=>r.id===id?{...value,reply:running?text:value.reply}:r)}:previous);
    if(running)timer=setTimeout(poll,650);
   }catch(e){if(!disposed){setError((e as Error).message);timer=setTimeout(poll,2000);}}
  }
  void poll();return()=>{disposed=true;clearTimeout(timer);};
 },[pending?.id,session?.id,root]);
 async function send(){
  setBusy(true);setError('');
  try{
   let current=session;
   if(!current){if(!selection)throw Error('请先选择正文。');current=await api<Session>(root+'/sessions',json('POST',{stage:record.kind,refs:[{id:record.id,version:record.version}],selection}));if(alive.current)setSession({...current,runs:[]});}
   const run=await api<Run>(root+'/sessions/'+current.id+'/messages',json('POST',{message,expected_version:current.version}));
   if(!alive.current)return;
   setSession({...current,version:current.version+1,runs:[...(current.runs||[]),run]});setMessage('');setDetail(null);
   await load(current.id);
  }catch(e){if(alive.current)setError((e as Error).message);}finally{if(alive.current)setBusy(false);}
 }
 async function action(work:()=>Promise<void>){setBusy(true);setError('');try{await work();}catch(e){if(alive.current){setError((e as Error).message);requestAnimationFrame(()=>area.current?.scrollIntoView?.({block:'nearest'}));}}finally{if(alive.current)setBusy(false);}}
 const bound=session?.selection||selection;
 const currentRun=session?.runs?.find(r=>r.proposals?.some(p=>p.id===detail?.id));
 return <Drawer title="选段 AI 修改" onClose={()=>{if(!busy)onClose();}}>
  {busy&&<p className="notice" role="status">正在处理，请等待本次操作结束后关闭面板。</p>}
  <p className="muted">只改固定选段，先提出候选；核对并明确采用后才保存新版本。采用后需要重新审核。</p>
  {history.length>0&&<label>历史选段讨论<select aria-label="历史选段讨论" value={session?.id||''} disabled={busy||active} onChange={e=>{setDetail(null);setError('');if(e.target.value)void action(()=>load(e.target.value));else setSession(null);}}><option value="">新建选段讨论</option>{history.map(s=><option key={s.id} value={s.id}>v{s.refs[0]?.version} · {s.selection.text.slice(0,35)} · {s.id.slice(0,6)}</option>)}</select></label>}
  {bound?<><h3>固定选段 · v{session?.refs[0]?.version||record.version}</h3><blockquote className="text-preview">{bound.text}</blockquote></>:<p>请先在正文中选择文字，再点击“选段 AI 修改”；也可查看历史讨论。</p>}
  {session?.runs?.map(run=><section className="agent-proposal" id={"selection-run-"+run.id} tabIndex={-1} key={run.id}>
   <strong>{run.message}</strong><p className="text-preview">{run.reply||(['queued','running'].includes(run.status)?'Pi 正在回复…':'尚无完整回复')}</p><small>{['queued','running'].includes(run.status)&&run.pause_requested?'正在暂停，等待收尾':run.status==='paused'&&run.checkpoint?.reason==='tools_recovered'?'结果已补回，原任务已暂停':run.status==='paused'&&run.checkpoint?.reason==='manual_pause'?'已暂停':statusName[run.status]||run.status} · {run.tool_calls||0}次工具调用</small><small> · {run.usage?.totalTokens?`${run.usage.totalTokens} tokens`:'用量未知'} · 金额未知</small>{run.status==='paused'?<p className="muted">{run.checkpoint?.reason==='tools_recovered'?'结果已补回，原任务已暂停；请明确续接或结束。':run.checkpoint?.reason==='manual_pause'?'已按请求停止新派发，原任务与选段已保留；继续仍需明确授权。':'本段额度已用完，请明确续接或结束回复。'}</p>:run.status==='continued'?<p className="muted">此段已续接，原额度记录保留。</p>:<ErrorNote message={run.error}/>}
   {run.proposals?.map(p=><div key={p.id}><Badge source={p.source}/><button disabled={busy} onClick={()=>void action(async()=>{const value=await api<Proposal>(root+'/proposals/'+p.id);if(alive.current)setDetail(value);})}>{p.title} · {p.status==='adopted'?'已采用':p.status==='rejected'?'已拒绝':'查看候选'}</button></div>)}
   {['queued','running'].includes(run.status)&&<PauseToCheckpoint key={run.id} endpoint={root+'/runs/'+run.id+'/pause'} requested={!!run.pause_requested} focusId={'selection-checkpoint-'+run.id} fallbackId={'selection-run-'+run.id} onChanged={()=>load(session.id)}/>}
   {['queued','running','paused'].includes(run.status)&&<button disabled={busy} onClick={()=>void action(async()=>{await api(root+'/runs/'+run.id+'/cancel',json('POST',{}));await load(session.id);})}>结束本次回复</button>}
   {needsToolReceiptRecovery(run.status,run.checkpoint)&&<ToolReceiptRecovery key={run.id} endpoint={root+'/runs/'+run.id} cancelEndpoint={root+'/runs/'+run.id+'/cancel'} expectedVersion={session.version} focusId={'selection-checkpoint-'+run.id} onChanged={async()=>{setConfirmed('');await load(session.id);}}/>}
   {run.status==='paused'&&<div id={'selection-checkpoint-'+run.id} tabIndex={-1}><p>本段模型请求 {run.checkpoint?.model_requests??'未知'}/20 · 工具派发 {run.checkpoint?.tool_calls??'未知'}/50</p>{run.checkpoint?.session_saved&&run.checkpoint.unreturned_models===0&&run.checkpoint.unresolved_tools===0?<><label style={{display:'flex',flexDirection:'row',alignItems:'flex-start'}}><input type="checkbox" checked={confirmed===run.id} disabled={busy} onChange={e=>setConfirmed(e.target.checked?run.id:'')}/>已核对原固定选段，授权新增最多20次模型请求和50次工具派发；费用未知。</label><button className="primary" style={{'--focus-color':'var(--surface)'} as React.CSSProperties} disabled={busy||confirmed!==run.id} onClick={()=>void action(async()=>{await api(root+'/runs/'+run.id+'/continue',json('POST',{confirm:true,expected_version:session.version}));setConfirmed('');await load(session.id);})}>明确续接此检查点</button></>:<p>检查点仍有未决调用或会话不完整，不能续接；请核对原回执。</p>}</div>}
  </section>)}
  {detail&&<section className="agent-proposal"><h3>{detail.title}</h3><Badge source={detail.source}/><p>修改前</p><pre>{detail.changes[0].selection?.text}</pre><p>建议替换</p><pre>{detail.changes[0].patch.text||'（删除所选文字）'}</pre>
   {detail.status==='pending'?<div className="actions"><button disabled={busy} onClick={()=>void action(async()=>{await api(root+'/proposals/'+detail.id+'/reject',json('POST',{}));setDetail({...detail,status:'rejected'});if(session)await load(session.id);})}>拒绝候选</button><button className="primary" style={{'--focus-color':'var(--surface)'} as React.CSSProperties} disabled={busy||currentRun?.status!=='completed'} onClick={()=>void action(async()=>{await onApply(detail);if(alive.current){setDetail({...detail,status:'adopted'});if(session)await load(session.id);}})}>采用选段修改并保存</button></div>:<p>{detail.status==='adopted'?'已采用；原版本保留':'已拒绝；原稿未改动'}</p>}
  </section>}
  <div ref={area}><ErrorNote message={error}/></div>
  {session&&session.refs[0]?.version!==record.version&&<p className="notice">正文已更新。此处保留原选段历史；请关闭并重新选择正文以继续修改。</p>}
  <label>修改要求或问题<textarea value={message} onChange={e=>setMessage(e.target.value)} placeholder="例如：突出犹豫，保留原情节。也可只询问选段信息。" maxLength={20000}/></label>
  <button className="primary" style={{'--focus-color':'var(--surface)'} as React.CSSProperties} disabled={busy||active||paused||!message.trim()||!bound||!!session&&session.refs[0]?.version!==record.version} onClick={()=>void send()}>{busy?'正在处理…':active?'Pi 正在回复…':'发送给 Pi'}</button>
 </Drawer>;
}
