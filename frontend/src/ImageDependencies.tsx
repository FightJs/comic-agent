import {useState} from 'react';
import type {RecordItem} from './api';
import {Select} from './Select';
import {Badge} from './ui';
import {primaryRecord} from './workflowLogic';

type Ref={id:string;version:number};
export function ImageDependencies({id,records,content,onChange}:{id:string;records:RecordItem[];content:any;onChange:(content:any)=>void}){
 const [selected,setSelected]=useState<Record<string,string>>({});
 return <section className="image-dependencies"><h3>前图连续性依赖</h3><p className="muted">仅用于动作、空间与状态衔接，人物身份和画风仍以批准资产为准。生成依赖包须一起勾选进入批次；前图采用并审核通过后，明确恢复批次才会继续。</p>
 {([['generation_dependencies','生成依赖包','添加生成依赖','package'],['previous_image_dependencies','已有前图','添加已有前图','image']] as const).map(([field,label,button,kind])=>{
  const raw=content[field],valid=raw===undefined||(Array.isArray(raw)&&raw.every((r:any)=>r&&typeof r.id==='string'&&Number.isInteger(r.version)));
  const refs:Ref[]=valid?(raw||[]):[];
  const choices=records.filter(r=>r.id!==id&&r.kind===kind&&primaryRecord(r)&&r.adopted===r.version&&!refs.some(ref=>ref.id===r.id)&&(kind!=='image'||r.review==='approved'&&r.content.url));
  return <div key={field}><h4>{label}</h4>{!valid?<p className="notice">保存的依赖格式无效，生成会被阻止。<button onClick={()=>onChange({...content,[field]:[]})}>清空无效{label}</button></p>:<>
   {!refs.length&&<p className="muted">尚未绑定{label}</p>}
   {refs.map((ref,index)=>{const record=records.find(r=>r.id===ref.id);return <div className="image-dependency-row" key={ref.id+':'+index}><p><strong>{record?.title||ref.id}</strong> · v{ref.version}{record&&<Badge source={record.source}/>}<br/>{!record?'记录不可见，请移除后重新选择':record.version!==ref.version?`当前已为v${record.version}，请移除后重新绑定`:(kind==='image'&&(record.review!=='approved'||!primaryRecord(record)))?'前图尚未采用或审核未通过':''}</p><button onClick={()=>onChange({...content,[field]:refs.filter((_,i)=>i!==index)})}>移除依赖 · {record?.title||ref.id}</button></div>;})}
   <div className="actions"><Select aria-label={label} value={selected[field]||''} disabled={refs.length>=8} onChange={e=>setSelected({...selected,[field]:e.target.value})}><option value="">选择{label}</option>{choices.map(r=><option key={r.id} value={r.id}>{r.title} · v{r.version}</option>)}</Select><button disabled={!selected[field]||refs.length>=8} onClick={()=>{const r=choices.find(r=>r.id===selected[field]);if(r)onChange({...content,[field]:[...refs,{id:r.id,version:r.version}]});setSelected({...selected,[field]:''});}}>{button}</button></div>
  </>}</div>;
 })}</section>;
}
