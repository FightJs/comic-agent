import {useEffect,useRef,useState} from 'react';
import {api,ApiError,json} from './api';
import {ErrorNote} from './ui';
import './tool-receipt-recovery.css';
type Report={read_only:boolean;recovery_available:boolean;recovery:{recovery_id:string;status:string}|null;receipts:{call_id:string;name:string;state:string;host_saved:boolean;node_status:string|null}[]};
const states:Record<string,string>={host_saved_node_unconfirmed:'宿主已保存，运行端尚未确认',missing_or_legacy:'缺少对应记录或旧记录证据不足',mismatch:'调用身份、输入或结果摘要不一致',unverified:'证据不足，尚未验证',registered:'已登记，尚未确认返回',received:'运行端已接收',rejected:'运行端已拒绝',matched:'结果可核对',missing:'未找到保存结果',conflict:'记录冲突',pending:'等待核对',returned:'已返回',completed:'已登记',failed:'失败',unknown:'未知'};
export function needsToolReceiptRecovery(status:string,checkpoint?:{unresolved_tools?:number}){return ['failed','interrupted','error'].includes(status)||(status==='paused'&&(checkpoint?.unresolved_tools??0)>0);}
export function ToolReceiptRecovery({endpoint,expectedVersion,focusId,cancelEndpoint,onChanged}:{endpoint:string;expectedVersion?:number;focusId?:string;cancelEndpoint?:string;onChanged:()=>Promise<void>|void}){
 const [report,setReport]=useState<Report|null>(null),[busy,setBusy]=useState(false),[confirmed,setConfirmed]=useState(false),[error,setError]=useState(''),[saved,setSaved]=useState(false),[attempted,setAttempted]=useState(false),[ended,setEnded]=useState(false);
 const target=useRef(endpoint),generation=useRef(0),locked=useRef(false),recovered=useRef(false),area=useRef<HTMLDivElement>(null);
 useEffect(()=>{generation.current++;recovered.current=false;setReport(null);setConfirmed(false);setError('');setSaved(false);if(target.current!==endpoint){setAttempted(false);target.current=endpoint;}setEnded(false);setBusy(false);locked.current=false;return()=>{generation.current++;if(recovered.current&&focusId)requestAnimationFrame(()=>{const target=document.getElementById(focusId);(target?.querySelector<HTMLElement>('input,button')||target)?.focus();});};},[endpoint,expectedVersion,focusId]);
 async function act(recover=false){
  if(locked.current||(recover&&(!confirmed||!report?.recovery_available||saved||ended)))return;
  const ticket=generation.current;locked.current=true;setBusy(true);setError('');
  try{
   if(recover){setAttempted(true);await api(endpoint+'/recover-tools',json('POST',{confirm:true,...(expectedVersion===undefined?{}:{expected_version:expectedVersion})}));if(ticket!==generation.current)return;recovered.current=true;setSaved(true);setConfirmed(false);await onChanged();if(ticket===generation.current)area.current?.focus();}
   else{const value=await api<Report>(endpoint+'/tool-receipts');if(ticket===generation.current){setReport(value);if(['pending','failed'].includes(value.recovery?.status||''))setAttempted(true);}}
  }catch(e){if(ticket===generation.current)setError((e instanceof ApiError&&e.status===409?'状态冲突，核对记录与当前输入已保留；请重新核对后处理。':'')+(e as Error).message);}
  finally{if(ticket===generation.current){locked.current=false;setBusy(false);}}
 }
 async function endRecovery(){
  if(locked.current||saved||ended)return;
  const ticket=generation.current;locked.current=true;setBusy(true);setError('');
  try{await api(cancelEndpoint||endpoint+'/cancel',json('POST',{}));if(ticket!==generation.current)return;setEnded(true);setConfirmed(false);await onChanged();if(ticket===generation.current)area.current?.focus();}
  catch(e){if(ticket===generation.current)setError('结束恢复未确认，原核对记录与当前输入已保留。'+(e as Error).message);}
  finally{if(ticket===generation.current){locked.current=false;setBusy(false);}}
 }
 return <div className="tool-receipt-recovery" ref={area} tabIndex={-1} aria-label="工具回执核对">
  <button type="button" disabled={busy} onClick={()=>void act()}>{busy&&!report?'正在核对…':'核对工具回执'}</button>
  {report&&<><p>只核对调用记录；结果匹配不代表业务成功，未找到结果也不代表工具没有执行。</p>
   {report.receipts.length?<ul>{report.receipts.map(r=><li key={r.call_id}><strong>{r.name}</strong> · {states[r.state]||('未知核对状态：'+r.state)} · {r.host_saved?'宿主结果已保存':'宿主结果未确认'} · 运行记录：{r.node_status?(states[r.node_status]||('未知运行状态：'+r.node_status)):'无对应运行记录'}<small>调用编号：{r.call_id}</small></li>)}</ul>:<p>没有可显示的工具回执。</p>}
   {ended?<p role="status">已结束本次恢复；原调用、回执与历史结果保留，未发送输入未提交。</p>:saved?<p role="status">已补回保存结果。继续原任务仍需单独授权20次模型请求和50次工具派发。</p>:report.recovery_available?<><label><input type="checkbox" checked={confirmed} disabled={busy} onChange={e=>setConfirmed(e.target.checked)}/><span>仅补回已保存结果，不请求模型或执行工具</span></label><button type="button" disabled={!confirmed||busy} onClick={()=>void act(true)}>{busy?'正在补回…':'明确仅补回已保存结果'}</button></>:<p>缺少可恢复证据或当前状态不允许恢复；请保留原记录继续核对。</p>}
  </>}
  {!saved&&!ended&&(attempted||['pending','failed'].includes(report?.recovery?.status||''))&&<div><p>恢复可能已登记并占用原任务。结束本次恢复会取消原运行，保留调用、回执与历史结果，不请求模型或执行工具。</p><button type="button" disabled={busy} onClick={()=>void endRecovery()}>结束本次恢复</button></div>}
  <ErrorNote message={error}/>
 </div>;
}
