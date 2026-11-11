import {useEffect,useRef,useState} from 'react';
import {api,base,json} from './api';
import {Badge,ErrorNote} from './ui';
import {scriptFields,promptFields} from './workflowLogic';
import './agent-proposals.css';
export type ProposalSummary={id:string;title:string;status:string;source:string};
type Change={target:string;id:string;kind?:string;title:string;version?:number;revision?:number;before:Record<string,unknown>;patch:Record<string,unknown>;location?:{episode?:number;panel?:number};dependencies?:{id:string;title:string;kind:string;version:number}[];full_prompt_preserved?:boolean};
type Detail=ProposalSummary&{changes:Change[]};
const labels:Record<string,string>=Object.fromEntries([...scriptFields,...promptFields,['text','正文'],['prompt','完整提示词'],['label','名称'],['summary','摘要'],['aliases','别名'],['attributes','属性'],['important','重要实体'],['type','类型'],['relation','关系'],['reason','推断说明'],['inferred','是否推断'],['story_time','故事时间']]);
const show=(value:unknown)=>typeof value==='string'?value:JSON.stringify(value,null,2)??'未填写';
export function AgentProposal({pid,proposal,runStatus,onChanged}:{pid:string;proposal:ProposalSummary;runStatus:string;onChanged:()=>void|Promise<void>}){
  const [detail,setDetail]=useState<Detail|null>(null),[status,setStatus]=useState(proposal.status),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const area=useRef<HTMLDivElement>(null);
  useEffect(()=>{setStatus(proposal.status);},[proposal.status]);
  const endpoint=base(pid)+'/agent/proposals/'+proposal.id;
  async function open(){setBusy(true);setError('');try{setDetail(await api<Detail>(endpoint));}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function act(action:'adopt'|'reject'){
    if(!detail)return;setBusy(true);setError('');
    try{
      if(action==='adopt')for(const change of detail.changes){
        if([change.id,...(change.target==='script_delete'?(change.dependencies||[]).map(r=>r.id):[])].some(id=>localStorage.getItem(`comic-draft:${pid}:${id}`)))throw Error('目标仍有未保存草稿，请先保存或处理草稿，再采用。');
        if(change.target.startsWith('graph_')&&localStorage.getItem(`comic-graph-draft:${pid}`))throw Error('图谱仍有未保存草稿，请先处理，再采用。');
      }
      await api(endpoint+'/'+action,json('POST',{}));setStatus(action==='adopt'?'adopted':'rejected');
      if(action==='adopt'){window.dispatchEvent(new CustomEvent('comic-graph-changed',{detail:{pid}}));await onChanged();}
    }catch(e){setError((e as Error).message);requestAnimationFrame(()=>area.current?.scrollIntoView?.({block:'nearest'}));}finally{setBusy(false);}
  }
  return <section className="agent-proposal" aria-label={'修改候选：'+proposal.title}>
    <header><strong>{proposal.title}</strong><Badge source={proposal.source}/><span>{status==='adopted'?'已采用':status==='rejected'?'已拒绝':'待核对，尚未修改成品'}</span></header>
    {!detail?<button disabled={busy} onClick={()=>void open()}>{busy?'正在读取候选…':'查看修改候选'}</button>:<>
      {detail.changes.map((change,i)=><section className="agent-change" key={i}><h4>{change.title}{change.location?.episode?` · 第${change.location.episode}话${change.location.panel?`第${change.location.panel}格`:''}`:''} · {change.version?`v${change.version}`:`图谱r${change.revision}`}</h4>
        {(change.kind==='style'||change.kind==='asset')&&<p className="muted">本候选仅修改提示文本，不会自动生成或替换参考图。</p>}
        {change.target.startsWith('graph_')&&<p className="muted">图谱修改写入改编层，保留原著层及其证据；采用后可在改编视角查看。</p>}
        {change.kind==='outline'||change.kind==='skeleton'?<p className="muted">新正文按纯文本段落保存，旧版本保留。采用后需要重新审核。</p>:null}
        {change.full_prompt_preserved&&<p className="notice">当前是完整提示词覆盖模式：本候选只改分段，完整提示词保持不变。需要影响最终生图文本时，请另提完整提示词修改。</p>}
        {change.target==='script_create'&&<p className="notice">新增脚本 · 第{change.location?.episode}话第{String(change.patch.panel)}格</p>}
        {change.target==='script_create'&&<p className="muted">沿用参考格的话与批次，不重排已有格号；采用后需要审核。</p>}
        {change.target==='script_delete'&&<><p className="notice">删除此格，并撤下以下关联内容；保留历史版本，已有格号不重排。</p><pre>{show(change.before.description)}</pre><p>删除原因：{show(change.patch.reason)}</p><ul>{change.dependencies?.map(r=><li key={r.id}>{r.title} · v{r.version}（{r.kind==='script'?'脚本':r.kind==='package'?'生图包':r.kind==='image'?'图片':'试制确认'}）</li>)}</ul></>}
        {Object.entries(change.target==='script_delete'?{}:change.patch).map(([field,value])=><div className="agent-field-diff" key={field}><strong>{labels[field]||field}</strong><div><span>修改前</span><pre>{change.target==='script_create'?'新建内容':show(change.before[field])}</pre></div><div><span>建议内容</span><pre>{show(value)}</pre></div></div>)}
      </section>)}
      {status==='pending'&&<div className="actions"><button disabled={busy} onClick={()=>void act('reject')}>拒绝候选</button><button className="primary" disabled={busy||runStatus!=='completed'} onClick={()=>void act('adopt')}>采用这些修改</button>{runStatus!=='completed'&&<small>回复完整完成后才能采用。</small>}</div>}
    </>}
    <div ref={area}><ErrorNote message={error}/></div>
  </section>;
}
