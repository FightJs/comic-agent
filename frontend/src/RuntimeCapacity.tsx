import {useEffect,useRef,useState} from 'react';
import {api,ApiError,json} from './api';
import {Select} from './Select';
import {ErrorNote} from './ui';
import './runtime-capacity.css';

type Role='text'|'image'|'vision';
type Limits=Record<Role,number>;
type Draft={revision:number;limits:Limits};
type Snapshot=Draft&{usage:Record<Role,{limit:number;active:number;waiting:number}>};
const roles:Role[]=['text','image','vision'];
const names:Record<Role,string>={text:'文本',image:'图像',vision:'视觉检查'};
const storageKey='comic-runtime-capacity-draft';
function restored():Draft|null{
  try{
    const value=JSON.parse(sessionStorage.getItem(storageKey)||'null');
    return value&&Number.isInteger(value.revision)&&value.revision>=0&&roles.every(role=>Number.isInteger(value.limits?.[role])&&value.limits[role]>=1&&value.limits[role]<=8)?value:null;
  }catch{return null;}
}
export function RuntimeCapacity(){
  const [snapshot,setSnapshot]=useState<Snapshot|null>(null),[form,setForm]=useState<Draft|null>(restored);
  const [loading,setLoading]=useState(false),[saving,setSaving]=useState(false),[error,setError]=useState(''),[saved,setSaved]=useState(false),[saveConflict,setSaveConflict]=useState(false),[draftWarning,setDraftWarning]=useState('');
  const current=useRef(form),latest=useRef<Snapshot|null>(null),mounted=useRef(false),request=useRef(0),inFlight=useRef(false),writing=useRef(false);
  function edit(value:Draft){
    current.current=value;setForm(value);setSaved(false);
    try{sessionStorage.setItem(storageKey,JSON.stringify(value));setDraftWarning('');}catch{setDraftWarning('浏览器无法保存容量草稿。当前输入仍在本页；关闭设置或刷新会丢失，请先保存。');}
  }
  async function refresh(){
    if(inFlight.current||writing.current)return;
    inFlight.current=true;setLoading(true);const sequence=++request.current;
    try{
      const value=await api<Snapshot>('/runtime/limits');
      if(!mounted.current||sequence!==request.current)return;
      if(latest.current&&value.revision<latest.current.revision)return;
      latest.current=value;setSnapshot(value);
      if(!current.current){current.current={revision:value.revision,limits:{...value.limits}};setForm(current.current);}
    }catch(e){if(mounted.current&&sequence===request.current)setError((e as Error).message);}
    finally{inFlight.current=false;if(mounted.current)setLoading(false);}
  }
  useEffect(()=>{
    mounted.current=true;void refresh();
    const timer=window.setInterval(()=>void refresh(),3000);
    return()=>{mounted.current=false;request.current++;window.clearInterval(timer);};
  },[]);
  const conflict=Boolean(form&&snapshot&&(saveConflict||form.revision!==snapshot.revision));
  const dirty=Boolean(form&&snapshot&&roles.some(role=>form.limits[role]!==snapshot.limits[role]));
  async function save(){
    if(!form||!snapshot||saving||loading||conflict||!dirty)return;
    writing.current=true;setSaving(true);setError('');setSaved(false);request.current++;
    try{
      const value=await api<Snapshot>('/runtime/limits',json('PUT',{expected_revision:form.revision,limits:form.limits}));
      if(!mounted.current)return;
      latest.current=value;setSnapshot(value);current.current={revision:value.revision,limits:{...value.limits}};setForm(current.current);setSaveConflict(false);setSaved(true);
      try{sessionStorage.removeItem(storageKey);}catch{}
    }catch(e){
      if(mounted.current){setError((e as Error).message);if(e instanceof ApiError&&e.status===409)setSaveConflict(true);}
    }finally{
      writing.current=false;if(mounted.current){setSaving(false);void refresh();}
    }
  }
  return <section className="runtime-capacity" aria-labelledby="runtime-capacity-title">
    <div className="capacity-heading"><h3 id="runtime-capacity-title">共享运行容量</h3><button type="button" disabled={loading||saving} onClick={()=>{setError('');void refresh();}}>{loading?'刷新中…':'刷新运行状态'}</button></div>
    <p>所有项目共用。分别限制同时提交的文本、生图和看图任务；排队中的任务会在提交前重新核对输入与授权。</p>
    <ErrorNote message={error}/>
    {error&&snapshot&&<p className="capacity-help">当前显示上次读取的运行状态，请刷新核对。</p>}
    {!snapshot&&<p role="status">{loading?'正在读取运行容量…':'未能读取当前设置，请刷新后再调整。'}</p>}
    {snapshot&&form&&<>
      <div className="capacity-rows">{roles.map(role=><div className="capacity-row" key={role}>
        <div><strong>{names[role]}</strong><span>运行 {snapshot.usage[role].active} · 排队 {snapshot.usage[role].waiting}</span><small>当前已保存：{snapshot.limits[role]}</small></div>
        <label>{names[role]}同时运行上限<Select aria-label={names[role]+'同时运行上限'} disabled={saving} value={String(form.limits[role])} onChange={e=>{edit({...form,limits:{...form.limits,[role]:Number(e.target.value)}});setError('');}}>{Array.from({length:8},(_,i)=><option key={i+1} value={i+1}>{i+1}</option>)}</Select></label>
      </div>)}</div>
      <p className="capacity-help">范围 1–8。缩小上限不会中止已提交请求；在途收尾期间，运行数可能暂时高于新上限。容量不代表费用预算或供应商额度，PDF解析不计入这三类。</p>
      {conflict&&<div className="notice capacity-conflict"><p>运行容量已更新，当前输入已保留。请对照上方“当前已保存”数值，再决定是否覆盖。</p><button type="button" disabled={saving||loading||(saveConflict&&snapshot.revision===form.revision)} onClick={()=>{edit({...form,revision:snapshot.revision});setSaveConflict(false);setError('');}}>已核对最新设置，保留我的输入</button>{saveConflict&&snapshot.revision===form.revision&&<small>请先刷新运行状态，读取最新版本。</small>}</div>}
      <div className="capacity-actions"><button type="button" className="primary" disabled={saving||loading||conflict||!dirty} onClick={()=>void save()}>{saving?'保存中…':'保存运行容量'}</button>{(dirty||conflict)&&<button type="button" disabled={saving||loading} onClick={()=>{edit({revision:snapshot.revision,limits:{...snapshot.limits}});setSaveConflict(false);setError('');try{sessionStorage.removeItem(storageKey);}catch{}}}>还原为当前设置</button>}</div>
      {saved&&<p className="success" role="status">运行容量已保存</p>}
      {(dirty||conflict)&&<small className="capacity-help">{draftWarning||'容量调整尚未保存；当前标签页关闭设置或刷新后会恢复这份输入。'}</small>}
    </>}
  </section>;
}
