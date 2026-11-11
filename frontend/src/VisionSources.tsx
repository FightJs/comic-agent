import {useEffect,useState,useRef} from 'react';
import {api,base} from './api';
import {Select} from './Select';
import type {GraphDocument} from './graphTypes';
export type VisionSource={document_id:string;parse_version:number;start:number;end:number;title:string;quote:string};
export function VisionSources({pid,value,onChange,onError}:{pid:string;value:VisionSource[];onChange:(next:VisionSource[])=>void;onError:(message:string)=>void}){
 const [documents,setDocuments]=useState<GraphDocument[]>([]),[documentID,setDocumentID]=useState(''),[start,setStart]=useState(0),[end,setEnd]=useState(0),[chapter,setChapter]=useState(''),[reading,setReading]=useState(false),[picked,setPicked]=useState<VisionSource|null>(null);
 const readingVersion=useRef(0);
 function invalidate(){readingVersion.current++;setPicked(null);}
 useEffect(()=>{let alive=true;api<GraphDocument[]>(base(pid)+'/documents').then(docs=>{if(alive){setDocuments(docs);setDocumentID(docs[0]?.id||'');setEnd(Math.min(2000,docs[0]?.char_count||0));}}).catch(e=>{if(alive)onError(e.message);});return()=>{alive=false;readingVersion.current++;};},[pid]);
 const doc=documents.find(d=>d.id===documentID);
 const valid=doc&&Number.isInteger(start)&&Number.isInteger(end)&&start>=0&&start<end&&end<=doc.char_count&&end-start<=10000;
 async function read(){if(!valid||!doc)return;const version=++readingVersion.current;setReading(true);onError('');try{const data=await api<{text:string;start:number;end:number}>(base(pid)+`/documents/${doc.id}/text?parse_version=${doc.parse_version}&start=${start}&end=${end}`);if(version===readingVersion.current)setPicked({document_id:doc.id,parse_version:doc.parse_version,start:data.start,end:data.end,title:doc.title,quote:data.text});}catch(e){if(version===readingVersion.current)onError((e as Error).message);}finally{setReading(false);}}
 const total=value.reduce((sum,v)=>sum+v.end-v.start,0);
 return <div className="vision-sources">
  <details><summary>添加原著证据</summary><p>先读原文，再明确加入本次检查。最多10段、每段10000字、合计30000字；只核对所选范围，不代表已读全书。</p>
   {doc?<><label>选择原著<Select value={documentID} onChange={e=>{const next=documents.find(d=>d.id===e.target.value);setDocumentID(e.target.value);setStart(0);setEnd(Math.min(2000,next?.char_count||0));setChapter('');invalidate();}}>{documents.map(d=><option key={d.id} value={d.id}>{d.title} · 解析v{d.parse_version}</option>)}</Select></label>
    <label>从章节定位<Select value={chapter} onChange={e=>{setChapter(e.target.value);invalidate();const selected=doc.chapters.find(c=>String(c.index)===e.target.value);setStart(selected?.start||0);setEnd(Math.min(selected?.end||doc.char_count,(selected?.start||0)+10000));}}><option value="">自行选择字符范围</option>{doc.chapters.map(c=><option key={c.index} value={c.index}>{c.title}</option>)}</Select></label>
    <div className="form-grid"><label>原文起点<input type="number" min={0} max={doc.char_count} step={1} value={start} onChange={e=>{setStart(Number(e.target.value));invalidate();}}/></label><label>原文终点<input type="number" min={1} max={doc.char_count} step={1} value={end} onChange={e=>{setEnd(Number(e.target.value));invalidate();}}/></label></div>
    <p className="muted">字符位置从0起，终点不含在内。正文共{doc.char_count.toLocaleString()}字，解析v{doc.parse_version}。</p>{doc.warnings.map((warning,i)=><p className="notice" key={i}>{warning}</p>)}
    <button disabled={reading||!valid} onClick={()=>void read()}>{reading?'正在读取原文…':'读取这段原文'}</button>
    {picked&&<div><p>{picked.title} · 解析v{picked.parse_version} · {picked.start}–{picked.end}</p><blockquote className="vision-original">{picked.quote}</blockquote><button disabled={value.length>=10||total+picked.end-picked.start>30000||value.some(v=>v.document_id===picked.document_id&&v.parse_version===picked.parse_version&&v.start===picked.start&&v.end===picked.end)} onClick={()=>{onChange([...value,picked]);invalidate();}}>将这段加入检查</button></div>}
   </>:<p>暂无已解析原著。可先检查图片与参考；不要据此声称符合原著。</p>}
  </details>
  <details open={value.length>0}><summary>已加入原著 · {value.length} 段 / {total} 字</summary>{value.map((v,i)=><div key={`${v.document_id}:${v.parse_version}:${v.start}:${v.end}`}><p>原文{i+1}：{v.title} · 解析v{v.parse_version} · {v.start}–{v.end}</p><blockquote className="vision-original">{v.quote}</blockquote><button onClick={()=>onChange(value.filter((_,index)=>index!==i))}>移除原文{i+1}</button></div>)}{!value.length&&<p>未加入原著；模型只会收到图像及所选脚本/包。</p>}</details>
 </div>;
}
