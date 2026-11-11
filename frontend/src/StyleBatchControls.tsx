import {useEffect,useRef,useState} from 'react';
import {api,base,json} from './api';
import {ErrorNote} from './ui';
import {ImageAttemptEvidence} from './ImageGeneration';
export type StyleBatch={id:string;status:string;error?:string;payload:{mode:string;count:number;retry_policy?:{max_not_sent_retries:number};call_limits:{images:number;vision:number;image_network_attempts?:number}};runtime:{effective_seconds:number;remaining_seconds:number;uncertain_seconds:number};jobs:{id:string;call:{manifest:{provider:{model:string};parameters:{size:string}};status:string;attempts?:any}}[]};
const names:Record<string,string>={preparing:'正在准备固定预览',preview:'三张固定预览，尚未授权',queued:'等待开始',running:'正在连续生成',pausing:'正在暂停，等待在途收尾',paused:'已暂停，原授权与返回保留',completed:'三套返回已保存，仍需逐项采用和审核',needs_attention:'部分任务需核对，未自动重试',interrupted:'已中断，未自动继续',cancelled:'已停止后续派发',budget_exhausted:'已达有效运行硬限，停止新派发',preview_failed:'整组预览未完成，未授权生图'};
export function StyleBatchControls({pid,batch,stale,guard,onChanged}:{pid:string;batch:StyleBatch;stale:boolean;guard:()=>void;onChanged:()=>Promise<void>|void}){
 const [confirmed,setConfirmed]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');const alive=useRef(true),area=useRef<HTMLElement>(null),grantInput=useRef<HTMLInputElement>(null),pauseRequested=useRef(false);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[batch.id]);
 useEffect(()=>{if(!busy&&pauseRequested.current&&['paused','completed','cancelled','budget_exhausted','interrupted','needs_attention'].includes(batch.status)){pauseRequested.current=false;if(document.activeElement===document.body||area.current?.contains(document.activeElement)){(grantInput.current&&!grantInput.current.disabled?grantInput.current:area.current)?.focus();}}},[batch.status,busy]);
 const grant=batch.status==='preview'||['paused','interrupted','needs_attention'].includes(batch.status);
 const retries=batch.payload.retry_policy?.max_not_sent_retries,networkMax=batch.payload.call_limits.image_network_attempts;
 const legacy=retries===undefined&&networkMax===undefined;
 const valid=(legacy||(Number.isInteger(retries)&&retries!==undefined&&retries>=0&&retries<=4&&networkMax===3*(1+retries)))&&batch.payload.mode==='style_tests'&&batch.payload.count===3&&batch.jobs.length===3&&batch.payload.call_limits.images===3&&batch.payload.call_limits.vision===0;
 async function act(action:string){
  if(busy)return;setBusy(true);setError('');
  try{
   if(action==='pause')pauseRequested.current=true;
   if(action==='start'||action==='recover'){if(!confirmed||!valid||(stale&&action==='start'))throw Error('请核对原组三张及固定依据，再明确授权。');if(action==='start'||!stale)guard();}
   await api(base(pid)+'/image-batches/'+batch.id+'/'+action,json('POST',action==='recover'&&stale?{confirm:true,restore_only:true}:action==='start'||action==='recover'?{confirm:true}:{}));
   if(!alive.current)return;setConfirmed(false);await onChanged();
  }catch(e){if(alive.current)setError((e as Error).message);}finally{if(alive.current)setBusy(false);}
 }
 return <section ref={area} tabIndex={-1} className="style-batch-control" aria-label="三套画风整组任务"><h4>整组任务 · {names[batch.status]||batch.status}</h4>
  <p>固定A/B/C各1张，最多3次业务生图。{legacy?'历史记录未保存物理网络上限，尝试授权与剩余次数未知；不会补造额外重试授权。':<>最多{networkMax}次物理网络尝试，每张确认未发出时额外重试最多{retries}次。</>}不含视觉检查、采用或人工审核；未知、已响应或拒绝不重试。关闭面板不会取消已授权批次。</p>
  <dl className="style-test-basis"><dt>图像型号</dt><dd>{[...new Set(batch.jobs.map(j=>j.call.manifest.provider.model))].join('、')}</dd><dt>尺寸</dt><dd>{[...new Set(batch.jobs.map(j=>j.call.manifest.parameters.size))].join('、')} · 共3张</dd><dt>运行预算</dt><dd>有效运行 {Math.ceil(batch.runtime.effective_seconds)} 秒 · 剩余 {Math.floor(batch.runtime.remaining_seconds)} 秒{batch.runtime.uncertain_seconds>0?' · 含未观测时间上界':''}</dd></dl>
  {batch.jobs.some(j=>j.call.attempts)&&<details><summary>逐次网络尝试记录</summary>{batch.jobs.map((j,i)=><div key={j.id}><h5>方案 {String.fromCharCode(65+i)}</h5><ImageAttemptEvidence attempts={j.call.attempts}/></div>)}</details>}
  {batch.error&&<p className="notice">{batch.error}</p>}
  {!valid&&<p className="notice">固定三张预览不完整，不能授权启动；已有单图预览仍可核对。</p>}
  {stale&&batch.status!=='preview'&&<p className="notice">依据已变化：只核对和恢复已存原返回；未提交项会被宿主阻止，不会用旧输入继续生图。</p>}
  {grant&&valid&&<><label className="agent-continue-confirm"><input ref={grantInput} type="checkbox" checked={confirmed} disabled={busy||(stale&&batch.status==='preview')} onChange={e=>setConfirmed(e.target.checked)}/>{stale?'我已核对原调用，只授权恢复已存返回，不授权派发未提交项；不含采用或审核':'我已核对本组共有内容、三套提示词与图像型号，授权按预览固定业务次数及物理网络上限连续执行；费用未知，不含采用或审核'}</label><button className="primary" disabled={busy||!confirmed||(stale&&batch.status==='preview')} onClick={()=>void act(batch.status==='preview'?'start':'recover')}>{batch.status==='preview'?'确认并连续生成三张':stale?'核对并恢复原返回':'明确继续原批次'}</button></>}
  {['queued','running'].includes(batch.status)&&<button disabled={busy} onClick={()=>void act('pause')}>暂停整组新派发</button>}
  {['preparing','preview','queued','running','pausing','paused','interrupted','needs_attention','budget_exhausted','preview_failed'].includes(batch.status)&&<button disabled={busy} onClick={()=>void act('cancel')}>停止整组后续派发</button>}
  <ErrorNote message={error}/>
 </section>;
}
