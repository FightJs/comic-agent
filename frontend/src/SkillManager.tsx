import {useEffect,useRef,useState} from 'react';
import {api,base,json} from './api';
import {ErrorNote} from './ui';
import './skills.css';
import {SkillDependencies,type SkillDependency} from './SkillDependencies';
type Skill={dependencies?:SkillDependency[];hash:string;id:string;name:string;version:string;stages:string[];tags:string[];files:string[];entrypoint:string};
const stageNames:Record<string,string>={setup:'系统配置',memory:'理解与记忆',skeleton:'骨架',outline:'细纲',style:'画风',asset:'资产',script:'脚本',package:'生图包',image:'生图',review:'视觉审核'};
const drafts=new Map<string,{revision:number;hashes:string[]}>();
export function hasSkillDraft(pid?:string){return Boolean(pid&&drafts.has(pid));}
export function SkillManager({pid}:{pid?:string}){
  const [items,setItems]=useState<Skill[]>([]),[selected,setSelected]=useState<string[]>([]),[revision,setRevision]=useState(0),[query,setQuery]=useState(''),[page,setPage]=useState(0),[busy,setBusy]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState(''),[status,setStatus]=useState(''),[preview,setPreview]=useState<{name:string;text:string;hash:string;path:string;end:number;total_chars:number}|null>(null);
  const rulePanel=useRef<HTMLDivElement>(null),feedback=useRef<HTMLDivElement>(null);
  useEffect(()=>{if(error||status)feedback.current?.scrollIntoView?.({block:'nearest'});},[error,status]);
  useEffect(()=>{if(preview)rulePanel.current?.scrollIntoView?.({block:'nearest'});},[preview?.hash]);
  useEffect(()=>{let alive=true;Promise.all([api<Skill[]>('/skills'),pid?api<{revision:number;hashes:string[]}>(base(pid)+'/skills'):Promise.resolve({revision:0,hashes:[]})]).then(([list,value])=>{if(alive){setItems(list);const draft=pid?drafts.get(pid):null;setSelected(draft?.hashes||value.hashes);setRevision(draft?.revision??value.revision);if(draft&&draft.revision!==value.revision)setError('项目流程已有新选择；本次未保存选择已保留，请读取最新选择后核对。');}}).catch(e=>{if(alive)setError(e.message);}).finally(()=>{if(alive)setLoading(false);});return()=>{alive=false;};},[pid]);
  async function upload(file:File){
    setBusy(true);setError('');setStatus('');
    try{const value=await api<Skill>('/skills/import',{method:'POST',body:file});setItems(await api<Skill[]>('/skills'));setStatus(`已安装 ${value.name} v${value.version}；仅安装不会自动启用。`);setPage(0);setQuery('');}catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function save(){
    if(!pid)return;setBusy(true);setError('');setStatus('');
    try{const value=await api<{revision:number;hashes:string[]}>(base(pid)+'/skills',json('PUT',{expected_revision:revision,hashes:selected}));setRevision(value.revision);setSelected(value.hashes);drafts.delete(pid);setStatus('本项目流程已保存；从下一次AI运行开始生效，已有运行保留原版本。');}catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function read(item:Skill){
    try{const value=await api<any>('/skills/'+item.hash+'/resource?path='+encodeURIComponent(item.entrypoint));setPreview({name:item.name,...value});}catch(e){setError((e as Error).message);}
  }
  const matches=items.filter(s=>(s.id+' '+s.version+' '+s.name+' '+s.tags.join(' ')+' '+s.stages.map(v=>stageNames[v]||v).join(' ')).includes(query));
  return <section className="skill-manager" aria-label="风格与流程Skill">
    <h3>风格与流程 Skill</h3><p>按小说类型选择创意、节奏或一致性规则。流程包进入共享库，需在项目中明确启用；规则已用于对应阶段的AI讨论、文本生成和单图视觉检查；安装后需明确启用。</p>
    <label className="skill-upload">导入Skill包<input type="file" accept=".json,.zip,application/json,application/zip" disabled={busy||loading} onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)void upload(file);}}/></label>
    <small>comic-skill/v1 JSON，或含manifest.json的ZIP。文本资料包最多10MB；不运行包内脚本，不在流程包中放密钥或原著。</small>
    {loading?<p role="status">正在读取流程库…</p>:<>
      {!pid&&<p className="notice">这里管理共享流程库。进入项目后，在模型设置中勾选并保存该项目使用的流程。</p>}
      <label className="skill-search">查找流程<input value={query} placeholder="名称、标识、版本、风格或阶段" onChange={e=>{setQuery(e.target.value);setPage(0);}}/></label>
      <div className="skill-list">{matches.slice(page*20,(page+1)*20).map(item=><article className="skill-row" key={item.hash}>
        <label className="skill-choice">{pid&&<input type="checkbox" aria-label={`启用 ${item.name} v${item.version}`} checked={selected.includes(item.hash)} disabled={busy||selected.length>=20&&!selected.includes(item.hash)} onChange={e=>setSelected(prev=>{const hashes=e.target.checked?[...prev.filter(hash=>items.find(s=>s.hash===hash)?.id!==item.id),item.hash]:prev.filter(hash=>hash!==item.hash);if(pid)drafts.set(pid,{revision,hashes});return hashes;})}/>}<span><strong>{item.name}</strong><span>v{item.version} · {item.tags.join(' / ')||'未分类'}</span><small>适用：{item.stages.map(v=>stageNames[v]||v).join('、')}</small><small>固定版本 {item.hash.slice(0,12)} · {item.files.length} 份资料</small><SkillDependencies items={item.dependencies}/></span></label><button type="button" onClick={()=>void read(item)}>查看规则</button>
      </article>)}</div>
      {!matches.length&&<p className="muted">{items.length?'没有匹配流程，请修改查找条件。':'还没有安装流程包。导入后可按项目启用。'}</p>}
      {matches.length>20&&<div className="actions"><small>{page*20+1}–{Math.min((page+1)*20,matches.length)} / {matches.length}</small><button disabled={!page} onClick={()=>setPage(p=>p-1)}>上一页流程</button><button disabled={(page+1)*20>=matches.length} onClick={()=>setPage(p=>p+1)}>下一页流程</button></div>}
      {pid&&<div className="skill-save"><small>本项目选择 {selected.length}/20 项；同一流程只启用一个版本。</small><button className="primary" disabled={busy} onClick={()=>void save()}>保存本项目流程</button></div>}
    </>}
    {pid&&drafts.has(pid)&&<p className="notice">尚未保存的选择在本次应用内保留，刷新前请保存。<button disabled={busy} onClick={async()=>{try{const value=await api<{revision:number;hashes:string[]}>(base(pid)+'/skills');setSelected(value.hashes);setRevision(value.revision);drafts.delete(pid);setError('');setStatus('已读取最新选择。');}catch(e){setError((e as Error).message);}}}>放弃草稿，读取最新选择</button></p>}
    <div ref={feedback}><ErrorNote message={error}/>{status&&<p className="success" role="status">{status}</p>}</div>
    {preview&&<div className="skill-rule-preview" ref={rulePanel}><div className="actions"><strong>{preview.name} · 主规则</strong><button onClick={()=>setPreview(null)}>收起规则</button></div><pre>{preview.text}</pre>{preview.end<preview.total_chars&&<button onClick={async()=>{try{const next=await api<any>('/skills/'+preview.hash+'/resource?path='+encodeURIComponent(preview.path)+'&start='+preview.end);setPreview({...preview,text:preview.text+next.text,end:next.end});}catch(e){setError((e as Error).message);}}}>读取后续规则（已读{preview.end}/{preview.total_chars}字符）</button>}</div>}
  </section>;
}
