import {useRef,useState} from 'react';
import {api,base} from './api';
import {Drawer,ErrorNote} from './ui';
import './delivery-readiness.css';

type EvidenceRef={id:string;version:number;source:string};
type Panel={episode:number|null;panel:number|null;script:EvidenceRef;images:EvidenceRef[];vision:{id:string;status:string;source:string;issue_count:number|null}|null;blockers:string[]};
type Result={status:'empty_scope'|'blocked'|'ready';summary:{source_panels:number;ready_panels:number;blocked_panels:number};panels:Panel[]};
type Props={pid:string;scope:string;episode:number;batch:number};
const reasons:Record<string,string>={
 invalid_source_identity:'脚本话格身份待核对',ambiguous_source:'同格多份脚本待核对',source_not_approved:'脚本待人工审核',source_not_adopted_current:'脚本最新版本尚未采用',
 unresolved_image_call:'图像调用待核对（含结果未知）',missing_image:'缺图',ambiguous_image:'同格多张主图待核对',missing_image_file:'图片文件待核对',image_not_approved:'图片待人工审核',image_not_adopted_current:'图片最新版本尚未采用',
 image_source_mismatch:'图片与当前脚本版本不匹配',image_package_mismatch:'图片与当前生图包版本不匹配',image_inputs_stale:'生图依据已过期',unresolved_image_issues:'人工记录有遗留问题',stale_visual_report:'视觉报告版本过期',unobserved:'未观察',unresolved_visual_issues:'视觉报告有遗留问题',visual_source_not_observed:'当前脚本未纳入视觉核对',
};
export function DeliveryReadiness({pid,scope,episode,batch}:Props){
 const [open,setOpen]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const [loaded,setLoaded]=useState<{pid:string;key:string;label:string;result:Result}|null>(null);
 const request=useRef(0);
 const query=scope==='episode'?`?episode=${episode}`:scope==='batch'?`?batch=${batch}`:'';
 const key=pid+query,label=scope==='episode'?`第${episode}话`:scope==='batch'?`第${batch}批（第${(batch-1)*10+1}–${batch*10}话）`:'全部已建脚本话格';
 const saved=loaded?.pid===pid?loaded:null;
 const old=!!saved&&(saved.key!==key||!!error||busy);
 const load=async()=>{
   setOpen(true);setBusy(true);setError('');const sequence=++request.current;
   try{const result=await api<Result>(base(pid)+'/delivery-readiness'+query);if(sequence===request.current)setLoaded({pid,key,label,result});}
   catch(e){if(sequence===request.current)setError((e as Error).message);}
   finally{if(sequence===request.current)setBusy(false);}
 };
 return <>
  <button onClick={()=>void load()} disabled={busy}>核对交付完整性</button>
  {open&&<Drawer title="交付完整性核对" wide onClose={()=>setOpen(false)}>
   <section className="delivery-readiness">
    <div className="delivery-readiness-toolbar"><strong>当前核对范围：{label}</strong><button disabled={busy} onClick={()=>void load()}>{busy?'正在核对…':'重新核对当前范围'}</button></div>
    <p className="delivery-readiness-note">只读取已建脚本对应的数据库证据，不调用模型、不改变采用或审核。像素文件未重新复核；核对结果和 ZIP 下载均不代表全话制作完成。</p>
    <ErrorNote message={error}/>
    {busy&&<p role="status">正在读取当前范围的数据库证据…</p>}
    {saved&&<div aria-live="polite">
      <p className="delivery-readiness-snapshot">{old?'上次数据':'本次读取快照'}：{saved.label}{old?'；请按当前范围重新核对。':''}</p>
      <p>{saved.result.status==='empty_scope'?'此范围没有当前有效源脚本，无法判定交付完整性。':saved.result.status==='ready'?'数据库证据未发现阻断；仍需人工确认实际图片与交付范围。':`源脚本 ${saved.result.summary.source_panels} 格，${saved.result.summary.blocked_panels} 格有待处理项，${saved.result.summary.ready_panels} 格未发现数据库阻断。`}</p>
      <ol className="delivery-readiness-panels">{saved.result.panels.map(p=><li key={p.script.id}>
        <strong>第{p.episode??'未知'}话 · 第{p.panel??'未知'}格</strong>
        {(p.script.source==='mock'||p.images.some(i=>i.source==='mock')||p.vision?.source==='mock')&&<span className="delivery-readiness-mock">模拟来源</span>}
        <p>{p.blockers.length?p.blockers.map(code=>reasons[code]||'存在待核对项').join('；'):'数据库证据未发现阻断'}</p>
        <small>脚本 {p.script.id} · v{p.script.version}{p.images.map(i=>` ｜ 图片 ${i.id} · v${i.version}`).join('')}{p.vision?` ｜ 视觉报告 ${p.vision.id}`:''}</small>
      </li>)}</ol>
    </div>}
   </section>
  </Drawer>}
 </>;
}
