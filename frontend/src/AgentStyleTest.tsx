import {useEffect,useRef,useState} from 'react';
import {api,base,json,type RecordItem} from './api';
import {primaryRecord} from './workflowLogic';
import {Badge,ErrorNote,reviewLabel} from './ui';
import {StyleBatchControls,type StyleBatch} from './StyleBatchControls';
import {ImageGeneration} from './ImageGeneration';
import {Select} from './Select';
import './style-tests.css';
type Summary={id:string;title:string;source:string};
type Plan={id:string;source:string;status:string;job_id:string|null;plan:{prompt:string;style_test:{option:string;features:{name:string;line:string;proportions:string;color:string;shadow:string}}};job?:{status:string;output?:RecordItem;call:{result?:{url?:string}}}};
type Group=Summary&{batch?:StyleBatch;stale:boolean;test:{representative:{character:string;appearance:string;scene:string;setting:string;action:string};basis:{outline:{id:string;title:string;version:number};sources:{record_id:string;title:string;start:number;end:number;quote:string}[]}};plans:Plan[]};
const labels:Record<string,string>={preview:'未授权生成',queued:'排队中',running:'生成中',succeeded:'候选已保存，待采用',unknown:'结果未知，先核对',received:'原返回待登记',interrupted:'已中断，先核对原调用',cancelled:'已停止',blocked:'输入变化，未提交',rejected:'请求被拒绝',resolved:'已记录人工结论'};
function stateLabel(plan:Plan){
 const output=plan.job?.output;
 if(output?.content.rejected)return '图片候选已拒绝';
 if(output&&primaryRecord(output)&&plan.job?.call.result?.url&&output.content.url!==plan.job.call.result.url)return '原测试图已被新版本替换；此处保留原返回';
 if(output&&primaryRecord(output))return '已采用 · '+reviewLabel(output.review)+'；画风确认仍须另行完成';
 if(output?.content.adopted_into)return '已采用到原画风；请核对原画风当前版本';
 return plan.job?labels[plan.job.status]||plan.job.status:plan.status==='rejected'?'方案已拒绝':'尚未创建图像预览';
}
export function AgentStyleTest({pid,summary,runStatus,records,onChanged}:{pid:string;summary:Summary;runStatus:string;records:RecordItem[];onChanged:()=>void|Promise<void>}){
 const [retryCount,setRetryCount]=useState(0);
 const [detail,setDetail]=useState<Group|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[opened,setOpened]=useState<{id:string;option:string}|null>(null);
 const alive=useRef(true),buttons=useRef<Record<string,HTMLButtonElement|null>>({});
 const endpoint=base(pid)+'/agent/style-tests/'+summary.id;
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[endpoint]);
 async function load(){const value=await api<Group>(endpoint);if(alive.current)setDetail(value);}
 useEffect(()=>{
  if(!detail||!(['preparing','queued','running','pausing'].includes(detail.batch?.status||'')||detail.plans.some(p=>p.job&&['queued','running'].includes(p.job.status))))return;
  let disposed=false,timer:ReturnType<typeof setTimeout>;
  async function poll(){try{const value=await api<Group>(endpoint);if(!disposed)setDetail(value);}catch(e){if(!disposed)setError((e as Error).message);}if(!disposed)timer=setTimeout(poll,1200);}
  timer=setTimeout(poll,1200);return()=>{disposed=true;clearTimeout(timer);};
 },[endpoint,detail?.batch?.status,detail?.plans.map(p=>p.job?.status).join(',')]);
 function guardDrafts(){
  if(!detail)return;
  if([detail.test.basis.outline.id,...detail.test.basis.sources.map(s=>s.record_id)].some(id=>localStorage.getItem(`comic-draft:${pid}:${id}`)))throw Error('测试依据有未保存草稿，请先保存或处理，再继续。');
 }
 async function previewGroup(){
  if(!detail||busy)return;setBusy(true);setError('');
  try{guardDrafts();await api(endpoint+'/batch-preview',json('POST',{max_not_sent_retries:retryCount}));if(!alive.current)return;await load();await onChanged();}
  catch(e){if(alive.current)setError((e as Error).message);}finally{if(alive.current)setBusy(false);}
 }
 async function preview(plan:Plan){
  if(plan.job_id){setOpened({id:plan.job_id,option:plan.plan.style_test.option});return;}
  if(!detail||busy)return;setBusy(true);setError('');
  try{
   guardDrafts();
   const job=await api<{id:string}>(base(pid)+'/agent/image-plans/'+plan.id+'/preview',json('POST',{max_not_sent_retries:retryCount}));
   if(!alive.current)return;
   setDetail(current=>current?{...current,plans:current.plans.map(p=>p.id===plan.id?{...p,job_id:job.id}:p)}:current);
   setOpened({id:job.id,option:plan.plan.style_test.option});await onChanged();
  }catch(e){if(alive.current)setError((e as Error).message);}finally{if(alive.current)setBusy(false);}
 }
 function close(){const option=opened?.option;setOpened(null);void load().catch(e=>{if(alive.current)setError(e.message);});requestAnimationFrame(()=>requestAnimationFrame(()=>{if(option)buttons.current[option]?.focus();}));}
 return <section className="agent-proposal style-test-group" aria-label="同组三套画风测试"><header><strong>{summary.title} · 三套画风测试</strong><Badge source={summary.source}/></header>
  <p>同一主角与主场景，每套一张身份、多视角、表情及剧情场景测试板。可逐套预览，或核对整组三张后一次明确授权连续生成；共3次业务生图，所选技术重试另有固定网络上限；讨论和查看方案不会生图。</p>
  {summary.source==='mock'&&<p className="notice">含模拟来源，图像候选会保留标记，不能当作正式放行；明确生成仍会调用已配置图像模型。</p>}
  <button disabled={busy} onClick={async()=>{setBusy(true);setError('');try{await load();}catch(e){if(alive.current)setError((e as Error).message);}finally{if(alive.current)setBusy(false);}}}>查看三套画风方案</button>
  {detail&&<div className="style-test-detail">
   {detail.stale&&<p className="notice" role="status">固定依据已变化，旧方案和原返回保留；未提交的图像不能继续生成，请重新讨论。已有任务仍可核对原调用。</p>}
   <h4>三套共同内容</h4><dl className="style-test-basis"><dt>主角</dt><dd>{detail.test.representative.character}</dd><dt>外观与衣装</dt><dd>{detail.test.representative.appearance}</dd><dt>主场景</dt><dd>{detail.test.representative.scene}</dd><dt>环境</dt><dd>{detail.test.representative.setting}</dd><dt>剧情动作</dt><dd>{detail.test.representative.action}</dd><dt>固定细纲</dt><dd>{detail.test.basis.outline.title} · v{detail.test.basis.outline.version}</dd></dl>
   <p className="muted">共有内容由AI提出，引用仅证明所列原文存在；外观补充、动作和画风效果仍须你核对。</p>
   <details><summary>查看固定原著证据 · {detail.test.basis.sources.length}段</summary>{detail.test.basis.sources.map((s,i)=><blockquote key={i}><small>{s.title} · 字符{s.start}–{s.end}</small><p>{s.quote}</p></blockquote>)}</details>
   {!detail.batch&&<><label>未发出时额外技术重试次数<Select aria-label="未发出时额外技术重试次数" value={retryCount} disabled={busy||detail.stale} onChange={e=>setRetryCount(Number(e.target.value))}>{[0,1,2,3,4].map(n=><option key={n} value={n}>{n===0?'0次（默认，不额外重试）':n+'次'}</option>)}</Select></label><p>将固定到新建单图或整组预览；已有任务保留原策略。仅确认未发出时重试，未知、已响应或拒绝不重试；费用未知。</p></>}
   {detail.batch?<StyleBatchControls key={detail.batch.id} pid={pid} batch={detail.batch} stale={detail.stale} guard={guardDrafts} onChanged={async()=>{await load();await onChanged();}}/>:<button disabled={busy||detail.stale||runStatus!=='completed'} onClick={()=>void previewGroup()}>预览整组三张</button>}
   <div className="style-test-comparison">{detail.plans.map(plan=>{const {option,features}=plan.plan.style_test;return <section key={plan.id} aria-label={'画风测试方案 '+option}>
    <h5>方案 {option} · {features.name}</h5><dl><dt>线条</dt><dd>{features.line}</dd><dt>比例</dt><dd>{features.proportions}</dd><dt>上色</dt><dd>{features.color}</dd><dt>阴影</dt><dd>{features.shadow}</dd></dl>
    {plan.job?.call.result?.url&&<figure><img src={plan.job.call.result.url} alt={'方案 '+option+' 的实际测试板返回'}/><figcaption>实际保存返回；不代表已采用或审核通过。</figcaption></figure>}
    <p className="status-text">{stateLabel(plan)}</p>
    <details><summary>完整固定提示词</summary><pre>{plan.plan.prompt}</pre></details>
    <button ref={node=>{buttons.current[option]=node;}} disabled={busy||(!plan.job_id&&(runStatus!=='completed'||detail.stale||plan.status==='rejected'))} onClick={()=>void preview(plan)}>{plan.job_id?'查看方案 '+option+' 的图像任务':'预览方案 '+option}</button>
   </section>;})}</div>
   {runStatus!=='completed'&&<p className="notice">回复完整完成后才能创建图像预览，暂停或中断不构成生成授权。</p>}
  </div>}
  <ErrorNote message={error}/>
  {opened&&<ImageGeneration pid={pid} kind="style" jobId={opened.id} records={records} refresh={async()=>{await onChanged();await load();}} onClose={close}/>}
 </section>;
}
