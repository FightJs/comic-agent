import {useEffect,useRef,useState} from 'react';
import {api,base,json} from './api';
import {Select} from './Select';
import {ErrorNote} from './ui';
import './model-capabilities.css';
type Kind='text'|'tool'|'vision'|'generation'|'edit';
type Capability={kind:Kind;status:'unverified'|'verified'|'stale';source:'real'|'mock'|'unknown';profile_hash?:string;observed_at?:string;receipt?:{type:string;id:string}|null;limits?:unknown;reason_codes?:string[]};
type Candidate={kind:Kind;receipt_id:string;label:string;source:'real'|'mock'|'unknown';observed_at?:string};
type Report={capabilities:Capability[];candidates:Candidate[]};
const kinds:Kind[]=['text','tool','vision','generation','edit'];
const names:Record<Kind,string>={text:'文本回复',tool:'工具调用',vision:'视觉理解',generation:'图像生成',edit:'图像编辑'};
const routes:Record<Kind,string>={text:'阶段讨论',tool:'支持查询工具的阶段讨论',vision:'图片的视觉检查',generation:'单图或批次生图',edit:'图片重生成或编辑'};
const statuses={unverified:'未验证',verified:'回执已核对',stale:'已过期'};
const sources={real:'真实调用回执',mock:'含模拟来源',unknown:'供应商实测未确认'};
const reasons:Record<string,string>={no_checked_receipt:'尚无已保存的核对回执',tool_roundtrip_unproven:'尚无完整工具调用与结果回传证据',profile_changed:'模型配置已变更，原核对结果已过期',no_evidence:'尚无可核对的回执',receipt_missing:'原回执不可用',receipt_incomplete:'原回执证据不完整',mock_source:'此记录含模拟来源，不证明真实供应商能力',source_unknown:'供应商实测未确认'};
function date(value?:string){if(!value)return '时间未知';const stamp=new Date(value);return Number.isNaN(stamp.getTime())?'时间未知':stamp.toLocaleString('zh-CN');}
function limits(value:unknown):string[]{
 if(typeof value==='string')return [value];
 if(Array.isArray(value))return value.filter((v):v is string=>typeof v==='string');
 if(value&&typeof value==='object')return Object.entries(value).map(([key,v])=>{
  if(key==='reference_count')return `图像参考数：${typeof v==='number'?v:'未知'}`;
  if(key==='image_count')return `实图数：${typeof v==='number'?v:'未知'}`;
  if(key==='mask_observed')return v===true?'观察到蒙版；不证明像素严格保留':v===false?'未观察到蒙版':'是否观察到蒙版未知';
  if(key==='semantic_quality_verified')return v===true?'回执包含语义质量核对声明；不替代人工审核':'语义质量未经验证';
  return '其他观察边界：'+(typeof v==='string'?v:JSON.stringify(v));
 });
 return [];
}
export function ModelCapabilities({pid,disabled=false}:{pid:string;disabled?:boolean}){
 const [report,setReport]=useState<Report|null>(null),[chosen,setChosen]=useState<Partial<Record<Kind,string>>>({}),[busy,setBusy]=useState(false),[error,setError]=useState(''),[status,setStatus]=useState('');
 const generation=useRef(0),locked=useRef(false),project=useRef(pid);
 const endpoint=base(pid)+'/model-capabilities';
 async function read(ticket=generation.current){
  if(disabled||locked.current)return;locked.current=true;setBusy(true);setError('');setStatus('');
  try{const value=await api<Report>(endpoint);if(ticket!==generation.current)return;setReport(value);setChosen(previous=>Object.fromEntries(Object.entries(previous).filter(([kind,id])=>value.candidates.some(c=>c.kind===kind&&c.receipt_id===id))));}
  catch(e){if(ticket===generation.current)setError((e as Error).message);}
  finally{if(ticket===generation.current){locked.current=false;setBusy(false);}}
 }
 useEffect(()=>{
  const ticket=++generation.current;locked.current=false;setBusy(false);setError('');setStatus('');
  if(project.current!==pid){project.current=pid;setReport(null);setChosen({});}
  if(!disabled)void read(ticket);
  return()=>{generation.current++;};
 },[endpoint,disabled]);
 const evidence=kinds.flatMap(kind=>{const receipt_id=chosen[kind];return receipt_id&&report?.candidates.some(c=>c.kind===kind&&c.receipt_id===receipt_id)?[{kind,receipt_id}]:[];});
 async function reconcile(){
  if(disabled||locked.current||!evidence.length)return;
  const ticket=generation.current;locked.current=true;setBusy(true);setError('');setStatus('');
  try{const value=await api<Report>(endpoint+'/reconcile',json('POST',{evidence}));if(ticket!==generation.current)return;setReport(value);setChosen({});setStatus('核对结果已保存；未请求模型或执行工具，也不表示质量或供应商整体能力通过。');}
  catch(e){if(ticket===generation.current)setError((e as Error).message+'；上次结果与本次选择已保留，请核对后重试。');}
  finally{if(ticket===generation.current){locked.current=false;setBusy(false);}}
 }
 return <section className="model-capabilities" aria-label="模型五类能力核对">
  <h3>模型能力回执核对</h3>
  <p>只核对本项目已有回执，不请求模型或执行工具，不读取密钥。保存只证明回执与配置的对应关系，不代表模型质量、所有场景或真实供应商完整能力通过。</p>
  {disabled&&<p className="notice">请先保存模型配置，再读取或核对能力结果。当前显示的记录不代表未保存配置。</p>}
  <button type="button" disabled={disabled||busy} onClick={()=>void read()}>{busy?'正在读取或核对…':'读取最新核对结果'}</button>
  {!report&&!disabled&&<p>{busy?'正在读取既有回执…':'尚未读取能力核对结果，请重试读取。'}</p>}
  {report&&<div className="model-capability-list">{kinds.map(kind=>{
   const value=report.capabilities.find(c=>c.kind===kind);const candidates=report.candidates.filter(c=>c.kind===kind);const boundary=limits(value?.limits);
   return <section key={kind} className="model-capability-row" aria-label={names[kind]+'能力'}>
    <div className="model-capability-heading"><h4>{names[kind]}</h4><span>{value?statuses[value.status]||'未验证':'未验证'}</span></div>
    {value&&<><p>{sources[value.source]||sources.unknown}{value.source==='mock'?'；可能包含模拟输入或模拟执行，不据此认定供应商为替身，也不证明真实供应商可用。':value.source==='unknown'?'；不能据此宣称真实供应商可用。':'；仅对应此回执与当时配置，不证明质量通过。'}</p>{value.observed_at&&<small>观察时间：{date(value.observed_at)}</small>}{value.reason_codes?.map(code=><p key={code} className="muted">{reasons[code]||'核对原因：'+code}</p>)}{boundary.length>0&&<ul className="model-capability-limits">{boundary.map((text,index)=><li key={index}>{text}</li>)}</ul>}{(value.receipt||value.profile_hash)&&<details><summary>回执与配置标识</summary>{value.receipt&&<p>{value.receipt.type} · {value.receipt.id}</p>}{value.profile_hash&&<p>配置标识：{value.profile_hash}</p>}</details>}</>}
    {candidates.length?<label>选择已有回执<Select aria-label={names[kind]+'已有回执'} value={chosen[kind]||''} disabled={disabled||busy} onChange={event=>{setChosen(old=>({...old,[kind]:event.target.value}));setStatus('');}}><option value="">暂不核对此类</option>{candidates.map(c=><option key={c.receipt_id} value={c.receipt_id}>{c.label} · {sources[c.source]||sources.unknown} · {date(c.observed_at)}</option>)}</Select></label>:<p className="muted">暂无可选回执。请先到{routes[kind]}入口，按正常流程明确授权任务；完成后再回来读取核对。</p>}
   </section>;
  })}</div>}
  <ErrorNote message={error}/>
  <button type="button" className="primary" disabled={disabled||busy||!evidence.length} onClick={()=>void reconcile()}>核对并保存结果</button>
  {status&&<p role="status">{status}</p>}
 </section>;
}
