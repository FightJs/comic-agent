import {ToolReceiptRecovery} from './ToolReceiptRecovery';
import {useState} from 'react';
import {api,base,json} from './api';
import {ErrorNote} from './ui';
import './production-continuation.css';
export function ProductionContinuation({pid,tid,checkpoint,onChanged}:{pid:string;tid:string;checkpoint:any;onChanged:()=>Promise<void>|void}){
 const [confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const clean=checkpoint?.session_saved===true&&checkpoint.unreturned_models===0&&checkpoint.unresolved_tools===0;
 async function resume(){if(!confirmed||busy)return;setBusy(true);setError('');try{await api(base(pid)+`/production-jobs/${tid}/attempts/${checkpoint.attempt_id}/continue`,json('POST',{confirm:true}));await onChanged();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <section className="production-continuation" id={'production-checkpoint-'+tid} tabIndex={-1} aria-label="生产暂停检查点"><h4>{checkpoint?.reason==='tools_recovered'?'结果已补回，原任务已暂停；请明确续接或结束':checkpoint?.reason==='manual_pause'?'已暂停，原任务与输入已保留':'额度已暂停，原任务与输入已保留'}</h4><p>本段模型请求 {checkpoint?.model_requests??'未知'}/20 · 工具派发 {checkpoint?.tool_calls??'未知'}/50。部分返回未生成候选，续接也不会自动采用。</p>{clean?<><p>继续原任务会增加一段调用额度；原输入、偏好、流程或模型已变化时会拒绝。输入框里的新意见不会加入本次续接。</p><label><input type="checkbox" disabled={busy} checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/><span>授权新增最多20次模型请求和50次工具派发；费用未知。</span></label><div className="actions"><button className="primary" disabled={!confirmed||busy} onClick={()=>void resume()}>{busy?'正在续接…':'明确续接此生产检查点'}</button></div></>:<p>检查点有未决调用或未保存完整会话，不能继续或普通重试；请先核对原回执。</p>}{checkpoint?.unresolved_tools>0&&<ToolReceiptRecovery cancelEndpoint={base(pid)+`/production-jobs/${tid}/cancel`} endpoint={base(pid)+`/production-jobs/${tid}/attempts/${checkpoint.attempt_id}`} focusId={'production-checkpoint-'+tid} onChanged={async()=>{setConfirmed(false);await onChanged();}}/>}<ErrorNote message={error}/></section>;
}
