import {useEffect,useRef,useState} from 'react';
import {api,ApiError,base,json} from './api';
import {ErrorNote} from './ui';
import './project-preferences.css';
type Preference={revision:number;text:string};
const credentialLike=(text:string)=>/\bsk-[A-Za-z0-9_-]{16,}|(?:api[_ -]?key|secret|bearer)\s*[:=]\s*['"]?\S{8,}/i.test(text);
const key=(pid:string)=>'comic-project-preference-draft:'+pid;
function restored(pid:string):Preference|null{
  try{const value=JSON.parse(sessionStorage.getItem(key(pid))||'null');if(typeof value?.text==='string'&&credentialLike(value.text)){sessionStorage.removeItem(key(pid));return null;}return value&&Number.isInteger(value.revision)&&value.revision>=0&&typeof value.text==='string'&&value.text.length<=6000&&!credentialLike(value.text)?value:null;}catch{return null;}
}
export function ProjectPreferences({pid}:{pid:string}){
  const [saved,setSaved]=useState<Preference|null>(null),[form,setForm]=useState<Preference|null>(()=>restored(pid));
  const [loading,setLoading]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[status,setStatus]=useState(''),[forcedConflict,setForcedConflict]=useState(false),[draftWarning,setDraftWarning]=useState('');
  const mounted=useRef(false),current=useRef(form),reading=useRef(false);
  const endpoint=base(pid)+'/preferences';
  function retain(value:Preference){
    current.current=value;setForm(value);setStatus('');
    if(credentialLike(value.text)){forgetDraft();setDraftWarning('输入疑似包含密钥，未写入浏览器草稿；请移到模型设置。');return;}
    try{sessionStorage.setItem(key(pid),JSON.stringify(value));setDraftWarning('');}catch{setDraftWarning('浏览器无法保存草稿；当前输入仍在本页，关闭或刷新前请先保存。');}
  }
  function forgetDraft(){try{sessionStorage.removeItem(key(pid));}catch{}}
  async function load(){
    if(reading.current)return;reading.current=true;setLoading(true);
    try{const value=await api<Preference>(endpoint);if(!mounted.current)return;setSaved(value);if(!current.current){current.current=value;setForm(value);}return value;}
    catch(e){if(mounted.current)setError((e as Error).message);}
    finally{reading.current=false;if(mounted.current)setLoading(false);}
  }
  useEffect(()=>{mounted.current=true;void load();return()=>{mounted.current=false;};},[pid]);
  const conflict=Boolean(saved&&form&&(forcedConflict||saved.revision!==form.revision));
  const dirty=Boolean(saved&&form&&saved.text!==form.text);
  async function commit(remove=false){
    if(!saved||!form||busy||loading||conflict||(!remove&&credentialLike(form.text)))return;
    const keep=remove&&dirty,prior=form.text;setBusy(true);setError('');setStatus('');
    try{
      const value=await api<Preference>(endpoint,json(remove?'DELETE':'PUT',remove?{expected_revision:form.revision}:{expected_revision:form.revision,text:form.text}));
      if(!mounted.current)return;setSaved(value);setForcedConflict(false);
      if(keep)retain({revision:value.revision,text:prior});else{current.current=value;setForm(value);forgetDraft();}
      setStatus(remove?keep?'已删除已保存偏好；未保存输入仍保留。':'已删除项目偏好，后续新运行不再加载。':'项目偏好已保存，后续新运行使用此版本。');
    }catch(e){if(mounted.current){setError((e as Error).message);if(e instanceof ApiError&&e.status===409){setForcedConflict(true);const latest=await load();if(latest&&mounted.current)setError('项目偏好已被更新；已读取最新保存内容，请核对后再保存。');}}}
    finally{if(mounted.current)setBusy(false);}
  }
  return <section className="project-preferences" aria-label="项目创作偏好管理">
    <p>明确保存风格、节奏或表达习惯，供本项目后续文本创作与阶段讨论使用。当前明确要求优先；偏好不是原著事实，也不会改变模型配置或审核授权。</p>
    <label>本项目创作偏好<textarea value={form?.text||''} rows={5} maxLength={6000} disabled={!saved||busy||loading} placeholder="例如：人物一致性优先，转折适度；台词保持简洁。" onChange={e=>{if(form)retain({...form,text:e.target.value});setError('');}}/></label>
    <div className="preference-meta"><small>{form?.text.length||0}/6000 字 · 未保存输入不参与 AI</small><button type="button" disabled={busy||loading} onClick={()=>{setError('');void load();}}>{loading?'读取中…':'读取最新已保存偏好'}</button></div>
    {saved&&<details className="preference-saved"><summary>查看已保存偏好 · v{saved.revision}{!saved.text?' · 未设置':''}</summary><p>{saved.text||'本项目当前未设置创作偏好。'}</p></details>}
    {conflict&&<div className="preference-conflict"><p>项目偏好已有新版本，当前输入保留。请展开上方已保存内容核对；不会自动覆盖。</p><button type="button" disabled={busy||loading||(forcedConflict&&saved?.revision===form?.revision)} onClick={()=>{if(form&&saved){retain({...form,revision:saved.revision});setForcedConflict(false);setError('');}}}>已核对最新偏好，保留我的输入</button>{forcedConflict&&saved?.revision===form?.revision&&<small>请先读取最新已保存偏好。</small>}</div>}
    <ErrorNote message={error}/>
    <div className="preference-actions"><button type="button" className="primary" disabled={!saved||busy||loading||conflict||!dirty||credentialLike(form?.text||'')} onClick={()=>void commit()}>保存项目偏好</button>{(dirty||conflict)&&<button type="button" disabled={busy||loading} onClick={()=>{if(saved){current.current=saved;setForm(saved);setForcedConflict(false);setError('');setStatus('');forgetDraft();}}}>还原为最新已保存偏好</button>}{saved?.text&&<button type="button" disabled={busy||loading||conflict} onClick={()=>void commit(true)}>删除已保存偏好</button>}</div>
    {status&&<p className="success" role="status">{status}</p>}
    {(dirty||conflict)&&<small className="preference-draft">{draftWarning||'本标签页会保留未保存输入；关闭设置或刷新后可恢复。'}</small>}
    <small className="preference-draft">保存或删除只影响后续新运行；在途任务与历史对话、输入快照保留原偏好。模型密钥请在模型设置中管理。</small>
  </section>;
}

export function ProjectPreferenceSettings({pid,title="项目创作偏好"}:{pid:string;title?:string}){
  const [open,setOpen]=useState(false);
  return <details className="agent-preferences" onToggle={event=>setOpen(event.currentTarget.open)}><summary>{title}</summary>{open&&<ProjectPreferences key={pid} pid={pid}/>}</details>;
}
