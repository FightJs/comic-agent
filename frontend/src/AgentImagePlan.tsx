import {useEffect,useRef,useState} from 'react';
import {api,base,json,type RecordItem} from './api';
import {Badge,ErrorNote} from './ui';
import {ImageGeneration} from './ImageGeneration';
import {Select} from './Select';
import type {ProposalSummary} from './AgentProposal';
import './agent-proposals.css';
import './agent-image-plan.css';
type Ref={id:string;title:string;version:number};
type Detail=ProposalSummary&{job_id?:string;plan:{kind:'style'|'asset';title:string;prompt:string;category:string;target:Ref|null;references:Ref[]}};
export function AgentImagePlan({pid,summary,runStatus,records,onChanged}:{pid:string;summary:ProposalSummary;runStatus:string;records:RecordItem[];onChanged:()=>void|Promise<void>}){
 const [retryCount,setRetryCount]=useState(0);
 const [detail,setDetail]=useState<Detail|null>(null),[status,setStatus]=useState(summary.status),[busy,setBusy]=useState(false),[error,setError]=useState(''),[jobId,setJobId]=useState('');
 useEffect(()=>setStatus(summary.status),[summary.status]);
 const previewButton=useRef<HTMLButtonElement>(null);
 function closePreview(){setJobId('');requestAnimationFrame(()=>requestAnimationFrame(()=>previewButton.current?.focus()));}
 const endpoint=base(pid)+'/agent/image-plans/'+summary.id;
 async function open(){setBusy(true);setError('');try{setDetail(await api<Detail>(endpoint));}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 async function preview(){if(!detail)return;setBusy(true);setError('');try{
   if([...(detail.plan.target?[detail.plan.target.id]:[]),...detail.plan.references.map(r=>r.id)].some(id=>localStorage.getItem(`comic-draft:${pid}:${id}`)))throw Error('目标或参考有未保存草稿，请先处理，再创建预览。');
   const job=await api<{id:string}>(endpoint+'/preview',json('POST',detail.job_id?{}:{max_not_sent_retries:retryCount}));setStatus('previewed');setDetail({...detail,status:'previewed',job_id:job.id});setJobId(job.id);await onChanged();
  }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 return <section className="agent-proposal agent-image-plan" aria-label="AI生图方案"><header><strong>生图方案 · {summary.title}</strong><Badge source={summary.source}/><span>{status==='rejected'?'已拒绝':status==='previewed'?'已有图像任务':'待核对方案'}</span></header><p>仅提出输入，不改原图、不自动生图。先核对预览中的型号、提示词和参考，再明确确认生成1张。</p>{summary.source==='mock'&&<p className="notice">方案含模拟来源，生成结果会保留此标记；确认生成仍会调用已配置的图像模型。</p>}<button disabled={busy} onClick={()=>void open()}>查看生图方案</button>
 {detail&&<div className="agent-change"><h4>{detail.plan.title} · {detail.plan.kind==='style'?'画风':detail.plan.category+'资产'}</h4><p>{detail.plan.target?`重生成“${detail.plan.target.title}” v${detail.plan.target.version}；原图保留。`:'新建一张候选图，生成后仍须明确采用。'}</p><pre>{detail.plan.prompt}</pre><h4>固定图片参考</h4>{detail.plan.references.length?<ul>{detail.plan.references.map(r=><li key={r.id}>{r.title} · v{r.version}</li>)}</ul>:<p>无附加图片参考。已有目标图会按实际输入作为底图。</p>}
 {!detail.job_id&&status!=='rejected'&&<><label>未发出时额外技术重试次数<Select aria-label="未发出时额外技术重试次数" value={retryCount} disabled={busy} onChange={e=>setRetryCount(Number(e.target.value))}>{[0,1,2,3,4].map(n=><option key={n} value={n}>{n===0?'0次（默认，不额外重试）':n+'次'}</option>)}</Select></label><p>仅确认请求未发出时按固定上限重试；结果未知、已收到响应或供应商拒绝均不重试。预览后策略固定，费用未知。</p></>}
 {status!=='rejected'&&<div className="actions">{status==='pending'&&<button disabled={busy} onClick={async()=>{setBusy(true);setError('');try{await api(endpoint+'/reject',json('POST',{}));setStatus('rejected');await onChanged();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>拒绝生图方案</button>}<button ref={previewButton} className="primary" disabled={busy||runStatus!=='completed'} onClick={()=>void preview()}>{status==='previewed'?'打开已有生图预览':'创建生图预览'}</button>{runStatus!=='completed'&&<small>回复完整完成后才能创建预览。</small>}</div>}</div>}
 <ErrorNote message={error}/>{jobId&&detail&&<ImageGeneration pid={pid} kind={detail.plan.kind} jobId={jobId} records={records} refresh={async()=>{await onChanged();}} onClose={closePreview}/>}</section>;
}
