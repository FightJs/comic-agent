import {VisionReviewButton} from "./VisionReview";
import {useEffect,useRef,useState} from 'react';
import {api,base,json,type RecordItem} from './api';
import {Drawer,ErrorNote,Badge} from './ui';
import {Select} from './Select';
import {primaryRecord} from './workflowLogic';
import {useViewState} from './useViewState';
import './image-generation.css';

export function ImageRetryChoice({value,disabled,onChange}:{value:number;disabled?:boolean;onChange:(n:number)=>void}){
 return <><label>未发出时额外技术重试次数<Select aria-label="未发出时额外技术重试次数" value={value} disabled={disabled} onChange={e=>onChange(Number(e.target.value))}>{[0,1,2,3,4].map(n=><option key={n} value={n}>{n===0?'0次（默认，不额外重试）':`${n}次`}</option>)}</Select></label><p className="muted">仅在确认请求未发出时，按本次授权上限技术重试；默认0次，不额外重试。结果未知、已收到响应或供应商拒绝均不重试；费用未知。预览后策略固定，变更须创建新预览。</p></>;
}
export function ImageAttemptEvidence({attempts}:{attempts:any}){
 const outcomes:Record<string,string>={not_sent:'已确认未发出',unknown:'结果未知',rejected:'供应商拒绝',received:'已收到响应',completed:'已完成'};
 const phases:Record<string,string>={pool_acquire:'连接池等待阶段',connect:'连接阶段',response_headers:'响应头阶段',response_body:'响应体阶段',unknown:'传输阶段未知'};
 return <details><summary>网络尝试与技术重试证据</summary>{attempts?<><p>最多{attempts.max_attempts??'未知'}次物理网络尝试 · 剩余{attempts.remaining_attempts??'未知'}次。恢复不会重置原授权或已用次数；剩余额度不表示一定允许重试。</p>{attempts.attempts?.length?<ol>{attempts.attempts.map((attempt:any)=><li key={attempt.sequence}>第{attempt.sequence}次 · {attempt.evidence?(outcomes[attempt.evidence.outcome]||'结果证据未知'):'尚无完成证据'} · {attempt.evidence?.response_started===true?'已开始响应':attempt.evidence?.response_started===false?'未开始响应':'响应是否开始未知'} · {phases[attempt.evidence?.transport_phase]||'传输阶段未知'}</li>)}</ol>:<p>尚无已登记的物理网络尝试。</p>}</>:<p>没有逐次网络尝试证据；历史是否尝试与剩余次数未知，不据此判定未执行。</p>}<p>未知、已收到响应或供应商拒绝不重试；恢复只沿用原回执与剩余授权，不会重置次数。</p></details>;
}
type Job={id:string;created?:string;status:string;error?:string;payload:any;call:any;output?:RecordItem;output_id?:string};
const labels:Record<string,string>={preview:'待确认输入',waiting_dependency:'等待前图采用与审核',queued:'等待生图',running:'正在请求图像模型',succeeded:'候选已保存',unknown:'供应商结果未知，待核对',received:'返回已保存，待恢复登记',interrupted:'已中断，可核对恢复',blocked:'未提交或被阻止',rejected:'供应商拒绝，未自动重试',cancelled:'已停止后续写入',resolved:'已记录人工核对结论'};
const active=(j:Job)=>['queued','running'].includes(j.status);
export function ImageGeneration({pid,kind,target,basis,records,refresh,onClose,jobId,annotationEdit}:{pid:string;jobId?:string;kind:'style'|'asset'|'image';target?:RecordItem;basis?:RecordItem;records:RecordItem[];refresh:()=>Promise<void>;onClose:()=>void;annotationEdit?:{annotationVersion:number;preserve?:string}}){
 const label=kind==='style'?'画风':kind==='asset'?'资产':'逐格图片';
 const actualTarget=target&&(records.find(r=>r.id===target.id)||target);
 const annotationMode=kind==='image'&&target?.kind==='image'&&!!target.content.url&&!!annotationEdit;
 const annotationStale=annotationMode&&actualTarget?.version!==target?.version;
 const key=annotationMode?`image-form:${pid}:annotation:${target!.id}:${target!.version}:${annotationEdit!.annotationVersion}`:`image-form:${pid}:${kind}:${basis?.id||target?.id||'new'}:${basis?.version||target?.version||0}`;
 const [title,setTitle]=useViewState(key+':title',!annotationMode&&basis?`第${basis.content.episode}话第${basis.content.panel}格图片`:target?.title||''),[prompt,setPrompt]=useViewState(key+':prompt',annotationMode?'':basis?.content.prompt||target?.content.prompt||target?.content.description||''),[category,setCategory]=useViewState(key+':category',target?.content.category||'人物');
 const [preserve,setPreserve]=useViewState(key+':preserve',annotationEdit?.preserve||'');
 const [maxRetries,setMaxRetries]=useState(0),[references,setReferences]=useState<string[]>([]),[jobs,setJobs]=useState<Job[]>([]),[selected,setSelected]=useState<Job|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[note,setNote]=useState(''),[confirmed,setConfirmed]=useState(false),[outcome,setOutcome]=useState('no_image');
 const token=useRef(crypto.randomUUID());const endpoint=base(pid)+'/image-jobs';
 useEffect(()=>{setNote('');setConfirmed(false);setOutcome('no_image');},[selected?.id]);
 const refs=kind==='image'&&!annotationMode?[]:records.filter(r=>['style','asset'].includes(r.kind)&&r.id!==target?.id&&primaryRecord(r)&&r.review==='approved'&&r.content.url);
 const limit=16-(actualTarget?.content.url?1:0)-(kind==='asset'?1:0);
 function visible(values:Job[]){if(kind!=='image')return values;if(annotationMode)return values.filter(j=>j.payload.annotation_edit&&j.payload.target?.id===target?.id);return values.filter(j=>!j.payload.annotation_edit&&(!basis||(j.payload.image_content?.episode===basis.content.episode&&j.payload.image_content?.panel===basis.content.panel)));}
 async function load(sync=false){if(jobId){const value=await api<Job>(endpoint+'/'+jobId);setJobs([value]);if(sync)setSelected(value);return;}setJobs(visible(await api<Job[]>(endpoint+'?kind='+kind)));if(sync&&selected)setSelected(await api<Job>(endpoint+'/'+selected.id));}
 useEffect(()=>{let alive=true;const loading=jobId?api<Job>(endpoint+'/'+jobId).then(value=>{if(alive){setJobs([value]);setSelected(value);}}):api<Job[]>(endpoint+'?kind='+kind).then(v=>{if(alive)setJobs(visible(v));});loading.catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[endpoint,kind,jobId,annotationMode,target?.id,basis?.content.episode,basis?.content.panel]);
 useEffect(()=>{
  if(!selected||!active(selected))return;
  let disposed=false,timer:ReturnType<typeof setTimeout>;
  async function poll(){try{const value=await api<Job>(endpoint+'/'+selected!.id);if(disposed)return;setSelected(value);if(active(value))timer=setTimeout(poll,700);else{await load();await refresh();}}catch(e){if(!disposed){setError((e as Error).message);timer=setTimeout(poll,2000);}}}
  timer=setTimeout(poll,500);return()=>{disposed=true;clearTimeout(timer);};
 },[selected?.id,selected?.status,endpoint]);
 function guard(ids:string[]){if(ids.some(id=>localStorage.getItem(`comic-draft:${pid}:${id}`)))throw Error('目标或参考仍有未保存草稿，请先保存或处理，再继续。');}
 function inputIds(){const fixed=selected?.payload.style_test?.basis;return [...Object.keys(selected?.payload.input_refs||{}),...(fixed?[fixed.outline.id,...fixed.sources.map((s:any)=>s.record_id)]:[])];}
 async function act(action:string){if(!selected)return;setBusy(true);setError('');try{if(action!=='cancel')guard(inputIds());const next=await api<Job>(endpoint+'/'+selected.id+'/'+action,json('POST',{}));setSelected(next);await load();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 async function decide(action:'adopt'|'reject'){if(!selected?.output)return;setBusy(true);setError('');try{if(action==='adopt')guard([...inputIds(),selected.output.id]);await api(base(pid)+'/candidates/'+selected.output.id+'/'+action,json('POST',{}));setSelected(await api<Job>(endpoint+'/'+selected.id));await load();await refresh();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 const output=selected?.output;const adopted=output&&(primaryRecord(output)||output.content.adopted_into);const rejected=output?.content.rejected;
 return <Drawer title={annotationMode?'按批注编辑候选':`${label}模型生图候选`} onClose={onClose} wide><div className="image-generation">
  <p className="notice">将调用已配置的图像模型。先预览再确认，每次最多提交1张；费用未知。保存图片不代表视觉检查通过，结果须明确采用。</p>
  <ErrorNote message={error}/>
  <div className="actions">{!jobId&&<button disabled={busy} onClick={()=>{setSelected(null);setError('');token.current=crypto.randomUUID();}}>填写新要求</button>}<button disabled={busy} onClick={()=>void load(true).catch(e=>setError(e.message))}>刷新任务</button></div>
  {!selected&&jobId?<p role="status">正在读取指定单格任务；若读取失败，请刷新或关闭后重开。</p>:!selected?<div className="image-generation-form">
   {annotationMode?<><p>固定底图“{target!.title}” v{target!.version} · 批注版本 v{annotationEdit!.annotationVersion}。底图自动引用；附加参考仅作补充，结果另存候选。</p><p className="notice">区域与保护要求是文字意图，非硬蒙版；不保证区域外像素锁定。请填写本次修改要求与需要保留的内容。</p>{annotationStale&&<p role="alert">底图版本已变化，请关闭后从当前图片重新打开按批注编辑。</p>}</>:<>{basis?<p>从“{basis.title}” v{basis.version}生成第{basis.content.episode}话第{basis.content.panel}格。完整提示词与参考从生图包读取；已有图时另存修改候选，保留现稿。</p>:null}<p>{kind==='image'?'只使用包内完整提示词及实际参考；目标图片会在预览中核对。修改包内容请关闭面板，保存生图包后重新打开。':actualTarget?`重新生成“${actualTarget.title}” v${actualTarget.version}，保留现稿。`:'新建一张候选图，采用后再审核。'}{kind==='asset'?' 自动引用已确认画风；请先确认一张实际画风图。':''}</p></>}
   <label>图片名称<input value={title} maxLength={200} onChange={e=>setTitle(e.target.value)}/></label>
   {kind==='asset'&&<label>资产分类<Select value={category} onChange={e=>setCategory(e.target.value)}>{['人物','场景','道具'].map(v=><option key={v}>{v}</option>)}</Select></label>}
   <label>{annotationMode?'修改要求':'完整生图提示词'}<textarea value={prompt} readOnly={kind==='image'&&!annotationMode} rows={7} maxLength={32000} onChange={e=>setPrompt(e.target.value)} placeholder={annotationMode?'说明要修改的批注问题、区域及目标效果':'人物、场景、构图、画风，以及需要保留或修改的内容'}/></label>
   {annotationMode&&<label>保留要求<textarea value={preserve} rows={3} maxLength={4000} onChange={e=>setPreserve(e.target.value)} placeholder="例如保留人物身份、服装、机位与画风；这些要求不保证像素锁定"/></label>}
   {(kind!=='image'||annotationMode)&&<details><summary>附加已审核参考 · {references.length} 张</summary>{refs.map(r=><label className="image-reference" key={r.id}><input type="checkbox" checked={references.includes(r.id)} disabled={references.length>=limit&&!references.includes(r.id)} onChange={e=>setReferences(v=>e.target.checked?[...v,r.id]:v.filter(id=>id!==r.id))}/>{r.title} · v{r.version}<Badge source={r.source}/></label>)}{!refs.length&&<p>{annotationMode?'暂无可追加的已审核参考图；固定底图仍会自动引用。':'暂无已审核的参考图；资产生成仍会自动绑定已确认画风。'}</p>}</details>}
   <ImageRetryChoice value={maxRetries} disabled={busy} onChange={n=>{setMaxRetries(n);token.current=crypto.randomUUID();}}/>
   <button className="primary" disabled={busy||annotationStale||!prompt.trim()||!title.trim()} onClick={async()=>{setBusy(true);setError('');try{if(annotationStale)throw Error('底图版本已变化，请关闭后重新打开。');const chosen=refs.filter(r=>references.includes(r.id));guard([...(!annotationMode&&basis?[basis.id]:[]),...(actualTarget?[actualTarget.id]:[]),...chosen.map(r=>r.id)]);const value=await api<Job>(endpoint,json('POST',{kind,title,prompt,category,...(annotationMode?{annotation_edit:{annotation_version:annotationEdit!.annotationVersion,preserve}}:{basis:basis?{id:basis.id,version:basis.version}:null}),target:actualTarget?{id:actualTarget.id,version:actualTarget.version}:null,references:chosen.map(r=>({id:r.id,version:r.version})),submission_id:token.current,max_not_sent_retries:maxRetries}));setSelected(value);await load();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>{busy?'正在核对…':annotationMode?'预览按批注编辑':'预览模型与输入'}</button>
  </div>:<section className="image-job-detail" aria-label="图像任务详情">
   <h3>{selected.payload.title} · {labels[selected.status]||selected.status}</h3>{selected.payload.image_batch_id&&<p className="notice">此单格由批次管理，启动或恢复请回到原批次；这里可核对结果、采用或记录人工结论。</p>}
   {selected.payload.annotation_edit?<><p className="notice">按批注编辑 · 底图“{records.find(r=>r.id===selected.payload.target?.id)?.title||selected.payload.target?.id}” v{selected.payload.target?.version} · 批注版本 v{selected.payload.annotation_edit.annotation_version}</p><p>区域与保护要求是文字意图，非硬蒙版；不保证区域外像素锁定。</p>{selected.payload.annotation_edit.preserve&&<p>本次固定保留要求：{selected.payload.annotation_edit.preserve}</p>}</>:kind==='image'&&selected.payload.image_content&&<p className="notice">第{selected.payload.image_content.episode}话第{selected.payload.image_content.panel}格 · 生图包 v{selected.payload.basis?.version}</p>}
   <dl><dt>图像型号</dt><dd>{selected.call.manifest.provider.model}</dd><dt>数量 / 尺寸</dt><dd>1 张 · {selected.call.manifest.parameters.size}</dd><dt>来源</dt><dd><Badge source={selected.call.manifest.source}/></dd></dl>
   <p className="notice">业务图像调用最多1次；{selected.call.attempts?.max_attempts!=null?`物理网络尝试最多${selected.call.attempts.max_attempts}次（含技术重试）`:selected.payload.retry_policy?`物理网络尝试最多${1+selected.payload.retry_policy.max_not_sent_retries}次（含技术重试）`:'历史网络尝试授权上限未知'}。{selected.payload.retry_policy?`本次固定额外技术重试${selected.payload.retry_policy.max_not_sent_retries}次。`:'历史任务未记录技术重试策略。'}费用未知。</p>
   <ImageAttemptEvidence attempts={selected.call.attempts}/>
   {selected.payload.dependencies_bound===false&&<p className="notice">实际前图尚未绑定，此处仅为提示词和依赖计划预览；请回批次查看依赖并在前图采用、审核后明确恢复。</p>}
   <details open={selected.status==='preview'}><summary>本次固定提示词和参考版本</summary><pre>{selected.payload.prompt}</pre>{selected.call.manifest.references.length?<ul>{selected.call.manifest.references.map((r:any)=><li key={r.id}>{records.find(v=>v.id===r.id)?.title||r.id} · v{r.version}</li>)}</ul>:<p>{selected.payload.dependencies_bound===false?"前图像素待绑定，当前无已固定图片参考。":"无图像参考，按文字生成。"}</p>}{selected.payload.target&&<p>目标固定版本 v{selected.payload.target.version}；不自动覆盖现稿。</p>}</details>
   {!selected.payload.image_batch_id&&selected.status==='preview'&&<button className="primary" disabled={busy} onClick={()=>void act('start')}>确认并生成1张</button>}
   {!selected.payload.image_batch_id&&['preview','queued','running'].includes(selected.status)&&<button disabled={busy} onClick={()=>void act('cancel')}>{selected.status==='preview'?'丢弃预览':'停止后续写入'}</button>}
   {!selected.payload.image_batch_id&&(['received','interrupted'].includes(selected.status)||(selected.status==='unknown'&&selected.call.has_saved_response))&&<button disabled={busy} onClick={()=>void act('recover')}>恢复原调用与登记</button>}
   {selected.error&&<p className="notice">{selected.error}</p>}
   {selected.call.result?.request_id&&<p>供应商请求编号：{selected.call.result.request_id}</p>}
   {selected.call.result?.url&&<figure><img className="image-job-result" src={selected.call.result.url} alt={selected.payload.title+'生成返回'}/><figcaption>供应商返回 · 保存不等于审核通过 · {selected.call.result.usage?`${selected.call.result.usage.total_tokens} tokens`:'用量未知'} · 金额未知</figcaption></figure>}
   {selected.status==='succeeded'&&output&&<VisionReviewButton target={output}/>}
   {selected.status==='succeeded'&&output&&<div className="actions">{adopted?<p role="status">已采用；{kind==='image'?'可到图片工作区查看，请另行核对模型报告与人工审核。':kind==='style'?'请审核当前版本，再明确确认画风。':'请在资产列表审核当前版本。'}</p>:rejected?<p role="status">已拒绝，原稿保留。</p>:<><button disabled={busy} onClick={()=>void decide('reject')}>拒绝图片候选</button><button className="primary" disabled={busy} onClick={()=>void decide('adopt')}>采用图片候选</button></>}</div>}
   {['unknown','received'].includes(selected.status)&&<details><summary>记录人工核对结论（不自动重试）</summary><p>先凭请求编号在供应商侧核对；本系统无法自动确认是否已出图或扣费。</p><label>核对结果<Select value={outcome} onChange={e=>setOutcome(e.target.value)}><option value="no_image">已核对未取得图片</option><option value="handled_externally">已在系统外处理图片</option></Select></label><label>核对依据<textarea rows={3} value={note} onChange={e=>setNote(e.target.value)} maxLength={2000}/></label><label className="image-confirmation"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>我已在供应商侧完成核对</label><button disabled={busy||!confirmed||!note.trim()} onClick={async()=>{setBusy(true);setError('');try{setSelected(await api<Job>(endpoint+'/'+selected.id+'/resolve',json('POST',{outcome,note,confirmed:true})));await load();}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>记录核对结论</button></details>}
  </section>}
  <details className="image-job-history" open><summary>{annotationMode?'本底图按批注编辑':kind==='image'?'本话格':`本项目${label}`}生图记录 · {jobs.length} 项</summary>{jobs.map(j=><button className="image-job-history-row" key={j.id} disabled={busy} onClick={()=>{setSelected(j);setError('');setConfirmed(false);setNote('');}}>{j.payload.title} · {labels[j.status]||j.status} · {j.payload.target?`目标v${j.payload.target.version}`:'新建'}{j.created?' · '+new Date(j.created).toLocaleString('zh-CN'):''}</button>)}{!jobs.length&&<p>尚无模型生图记录。预览不会提交供应商。</p>}</details>
 </div></Drawer>;
}
