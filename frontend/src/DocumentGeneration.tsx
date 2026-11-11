import {useRef,useState} from 'react';
import {base,api,json,type RecordItem} from './api';
import {Drawer,ErrorNote} from './ui';
import {Select} from './Select';
import {GroupResults} from './Workflow';
import {primaryRecord} from './workflowLogic';

export function DocumentGeneration({pid,kind,target,records,refresh,onClose}:{pid:string;kind:'skeleton'|'outline';target?:RecordItem;records:RecordItem[];refresh:()=>Promise<void>;onClose:()=>void}){
 const skeletons=records.filter(r=>r.kind==='skeleton'&&primaryRecord(r));
 const [basis,setBasis]=useState(skeletons.at(-1)?.id || ''),[instruction,setInstruction]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),[results,setResults]=useState(false);
 const token=useRef(crypto.randomUUID());
 const selected=skeletons.find(r=>r.id===basis);
 const label=kind==='skeleton'?'骨架':'细纲';
 return <><Drawer title={`生成${label}候选`} onClose={onClose}>
  <p style={{overflowWrap:'anywhere'}}>{target?`以“${target.title}” v${target.version}为改稿目标。`:`建立新的${label}。`}模型可查询固定原著和已启用流程，结果须核对采用，原稿不会自动替换。</p>
  {kind==='outline'&&<label>参考骨架<Select aria-label="参考骨架" value={basis} onChange={e=>setBasis(e.target.value)}><option value="">不引用骨架</option>{skeletons.map(r=><option key={r.id} value={r.id}>{r.title} · v{r.version}</option>)}</Select></label>}
  <label>本次生成要求<textarea rows={6} value={instruction} onChange={e=>setInstruction(e.target.value)} placeholder={kind==='skeleton'?'改编主线、人物弧线、节奏和需要保留的情节':'话数范围、每话重点、节奏和原著对应范围'}/></label>
  <p className="muted">将调用配置的文本模型。缺少原著或模型配置时会阻止生成；细纲的话索引在采用后建立，仍可校正。</p>
  <ErrorNote message={error}/>
  <button className="primary" disabled={busy} onClick={async()=>{try{setBusy(true);setError('');const refs=[target,...(kind==='outline'?[selected]:[])].filter(Boolean) as RecordItem[];if(refs.some(r=>localStorage.getItem(`comic-draft:${pid}:${r.id}`)))throw Error('参考或目标仍有未保存草稿，请先保存成功后再生成。');await api(base(pid)+'/production-jobs',json('POST',{operation:'document',document_kind:kind,refs:target?[{id:target.id,version:target.version}]:[],basis:kind==='outline'&&selected?[{id:selected.id,version:selected.version}]:[],instruction,submission_id:token.current}));await refresh();setResults(true);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>{busy?'正在提交…':`生成${label}候选`}</button>
 </Drawer>{results&&<GroupResults pid={pid} groups={[token.current]} refresh={refresh} onClose={onClose}/>}</>;
}
