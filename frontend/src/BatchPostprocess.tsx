import {scriptFields} from './workflowLogic';
import {Badge} from './ui';
import type {RecordItem} from './api';
const phases:Record<string,string>={paused:'已暂停后续检查/返修',pending:'等待生成后检查',reviewing:'正在检查实际像素',repairing:'正在进行一轮剧情返修',rechecking:'正在复查返修图',completed:'授权流程结果已保存',needs_attention:'自动流程需核对',interrupted:'已中断，等待明确恢复',cancelled:'已停止后续自动操作'};
export function BatchPostprocess({job,onReport,onRepair,busy=false}:{job:any;busy?:boolean;onReport:(id:string,target:RecordItem,event:React.MouseEvent<HTMLButtonElement>)=>void;onRepair:(event:React.MouseEvent<HTMLButtonElement>)=>void}){
 const post=job.payload.postprocess;if(!post)return null;
 const basis=post.plan.basis;
 return <section className="batch-postprocess"><h4>{phases[post.status]||post.status}</h4><p>固定视觉型号：{basis.provider.model} · {post.plan.policy==='review_repair'?'最多一次严重剧情返修及一次复查':'只检查，不自动返修'}</p>
  {post.error&&<p className="notice">{post.error}</p>}
  {post.needs_manual&&<p className="notice">仍需人工核对问题；自动流程已到上限，不再追加返修。保存报告不代表人工通过。</p>}
  <details><summary>固定检查依据与规则</summary><p>{basis.context.length}项文本 · {basis.sources.length}段原文 · {basis.review_skills.length}项审核流程</p>{!basis.sources.length&&<p>未提供原著片段，不能据此验证全书一致性。</p>}{basis.context.map((r:any)=><div key={r.id}><strong>{r.title} · v{r.version}</strong><Badge source={r.source}/>{r.kind==='package'?<pre>{r.content.prompt}</pre>:scriptFields.map(([key,label])=>r.content[key]&&<p key={key}>{label}：{r.content[key]}</p>)}</div>)}{basis.sources.map((source:any,i:number)=><div key={i}><p>原文{i+1}：{source.title} · 解析v{source.parse_version} · {source.start}–{source.end}</p><blockquote>{source.quote}</blockquote></div>)}{basis.review_skills.map((skill:any)=><details key={skill.hash}><summary>{skill.name} · v{skill.version}</summary>{skill.resources.map((r:any)=><div key={r.path}><p>{r.path}</p><pre>{r.text}</pre></div>)}</details>)}<details><summary>查看固定输入原始记录</summary><pre>{JSON.stringify(basis,null,2)}</pre></details></details>
  {([['inspection','原图检查',job.output],['reinspection','返修图复查',job.repair?.output]] as const).map(([key,label,target])=>{const review=job[key];return review&&<div key={key}><h4>{label} · {review.status==='completed'?'报告已保存':review.status==='unknown'?'结果未知，不重发':'尚未完成，请核对'}</h4>{review.report&&<><p>{review.report.summary}</p>{review.report.issues.map((issue:any,i:number)=><div key={i}><strong>{({critical:'严重',major:'重要',minor:'一般'} as Record<string,string>)[issue.severity]} · {({story:'剧情',identity:'身份',costume:'服饰',scene:'场景',style:'画风',text:'文字',artifact:'缺陷',uncertain:'证据不足'} as Record<string,string>)[issue.category]}</strong><p>{issue.description}</p><p>{issue.evidence}</p></div>)}</>}{target&&<button onClick={event=>onReport(review.id,target,event)}>查看完整{label}报告</button>}</div>;})}
  {job.repair&&<><p>返修图另存候选，原图仍保留；请选择合适的候选人工核对采用。前图依赖使用最终返修候选，仍须采用并审核。</p><button aria-disabled={busy} onClick={onRepair}>查看一轮返修图任务</button></>}
 </section>;
}
