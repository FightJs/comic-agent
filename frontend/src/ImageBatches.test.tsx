// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ImageBatches} from './ImageBatches';
import {Scripts} from './Production';
import {api,type RecordItem} from './api';
vi.mock('./api',async()=>({...await vi.importActual('./api'),api:vi.fn()}));
HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
afterEach(()=>{cleanup();vi.resetAllMocks();localStorage.clear();});
const packages=[1,2].map(i=>({id:'p'+i,project_id:'p',adopted:1,source:'manual',review:'approved',created:'t',updated:'t',version:1,title:'第1话第'+i+'格',kind:'package',content:{episode:1,panel:i,prompt:'完整提示词'+i}} as RecordItem));
const batch={id:'b',status:'preview',payload:{count:2},jobs:packages.map((p,i)=>({id:'j'+i,status:'preview',payload:{title:p.title,prompt:p.content.prompt,basis:{id:p.id,version:1},input_refs:{[p.id]:1},references:[]},call:{manifest:{source:'ai',references:[],provider:{model:'fixture-image'},parameters:{size:'1024x1536'}}}}))};
it('previews the entire selected batch and requires explicit authorization before any image call',async()=>{
 vi.mocked(api).mockImplementation(async(path,opts)=>opts?.method?path.endsWith('/start')?{...batch,status:'running'}:batch:{items:[],next_start:null,total:0});
 render(<ImageBatches pid="p" packages={packages} records={packages} refresh={async()=>{}} onClose={()=>{}}/>);
 fireEvent.click(screen.getByRole('button',{name:'预览所选2格'}));
 const start=await screen.findByRole('button',{name:'确认并连续生成2格'});
 expect(start).toHaveProperty('disabled',true);
 expect(screen.getByText('完整提示词1')).toBeTruthy();expect(screen.getByText('完整提示词2')).toBeTruthy();
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/start'))).toBe(false);
 fireEvent.click(screen.getByLabelText('已核对本批全部输入，授权逐格调用图像模型；费用未知。'));await waitFor(()=>expect(start).toHaveProperty('disabled',false));fireEvent.click(start);
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/start'))).toBe(true));
});
it('blocks batch authorization when any frozen input has an unsaved draft',async()=>{
 vi.mocked(api).mockImplementation(async(_path,opts)=>opts?.method?batch:{items:[],next_start:null,total:0});
 render(<ImageBatches pid="p" packages={packages} records={packages} refresh={async()=>{}} onClose={()=>{}}/>);
 fireEvent.click(screen.getByRole('button',{name:'预览所选2格'}));await screen.findByText('完整提示词1');
 localStorage.setItem('comic-draft:p:p2','draft');
 fireEvent.click(screen.getByLabelText('已核对本批全部输入，授权逐格调用图像模型；费用未知。'));const start=screen.getByRole('button',{name:'确认并连续生成2格'});await waitFor(()=>expect(start).toHaveProperty('disabled',false));fireEvent.click(start);
 expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('未保存'));
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/start'))).toBe(false);
});

it('keeps batch history reachable with no selected or visible package',async()=>{
 vi.mocked(api).mockResolvedValue({items:[],next_start:null,total:0});
 render(<Scripts pid="p" kind="package" records={[]} batch={1} episode={1} panel={1} onPanel={()=>{}} onLocation={()=>{}} onSaved={()=>{}} refresh={async()=>{}} run={async()=>{}}/>);
 fireEvent.click(screen.getByRole('button',{name:'批量图像任务'}));
 expect(await screen.findByRole('dialog',{name:'逐格图像批次'})).toBeTruthy();
});

it('keeps the single-job trigger focusable while fetching the nested drawer input',async()=>{
 let release!:(value:any)=>void;const pending=new Promise(resolve=>{release=resolve;});
 vi.mocked(api).mockImplementation(async(path,opts)=>path.includes('/records/p1?')?pending:path.endsWith('/image-jobs/j0')?{...batch.jobs[0],payload:{...batch.jobs[0].payload,image_batch_id:'b'}}:opts?.method?batch:{items:[],next_start:null,total:0});
 render(<ImageBatches pid="p" packages={packages} records={packages} refresh={async()=>{}} onClose={()=>{}}/>);
 fireEvent.click(screen.getByRole('button',{name:'预览所选2格'}));
 const trigger=await screen.findByRole('button',{name:'查看单格任务 · 第1话第1格'});await waitFor(()=>expect(trigger.getAttribute('aria-disabled')).toBe('false'));trigger.focus();fireEvent.click(trigger);
 expect(trigger).toHaveProperty('disabled',false);
 release(packages[0]);await screen.findByText('此单格由批次管理，启动或恢复请回到原批次；这里可核对结果、采用或记录人工结论。');
});
it('shows inherited mock provenance before the batch can be authorized',async()=>{
 const inherited={...batch,jobs:batch.jobs.map((job,i)=>i?job:{...job,call:{...job.call,manifest:{...job.call.manifest,source:'mock'}}})};
 vi.mocked(api).mockImplementation(async(_path,opts)=>opts?.method?inherited:{items:[],next_start:null,total:0});
 render(<ImageBatches pid="p" packages={packages} records={packages} refresh={async()=>{}} onClose={()=>{}}/>);
 fireEvent.click(screen.getByRole('button',{name:'预览所选2格'}));
 expect(await screen.findByText('模拟')).toBeTruthy();
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/start'))).toBe(false);
});

it('shows planned continuity references as unbound and waiting rather than a complete actual request',async()=>{
 const planned={...batch,status:'needs_attention',jobs:batch.jobs.map((j,i)=>i?j:{...j,status:'waiting_dependency',payload:{...j.payload,dependencies_bound:false,dependency_plan:{packages:[{id:'p2',version:1,title:'前格包'}],images:[]}}})};
 vi.mocked(api).mockImplementation(async(_path,opts)=>opts?.method?planned:{items:[],next_start:null,total:0});
 render(<ImageBatches pid="p" packages={packages} records={packages} refresh={async()=>{}} onClose={()=>{}}/>);
 fireEvent.click(screen.getByRole('button',{name:'预览所选2格'}));
 expect(await screen.findByText('等待前图采用与审核')).toBeTruthy();
 expect(screen.getByText(/实际前图尚未绑定/)).toBeTruthy();expect(screen.getByText(/前格包 · v1/)).toBeTruthy();
 expect(screen.getByRole('button',{name:'明确恢复原批次'})).toHaveProperty('disabled',true);
});

it.each(['original','repair'])('blocks dependency recovery when the %s candidate has an unsaved draft',async(kind)=>{
 const waiting={...batch,status:'needs_attention',jobs:batch.jobs.map((j,i)=>i?{...j,status:'waiting_dependency'}:{...j,status:'succeeded',output_id:'produced-image',repair:{...j,output_id:'repair-image'}})};
 vi.mocked(api).mockImplementation(async(_path,opts)=>opts?.method?waiting:{items:[],next_start:null,total:0});
 render(<ImageBatches pid="p" packages={packages} records={packages} refresh={async()=>{}} onClose={()=>{}}/>);
 fireEvent.click(screen.getByRole('button',{name:'预览所选2格'}));await screen.findByRole('button',{name:'明确恢复原批次'});
 localStorage.setItem(`comic-draft:p:${kind==='repair'?'repair-image':'produced-image'}`,'draft');fireEvent.click(screen.getByLabelText('已核对本批全部输入，授权逐格调用图像模型；费用未知。'));
 const resume=screen.getByRole('button',{name:'明确恢复原批次'});await waitFor(()=>expect(resume).toHaveProperty('disabled',false));fireEvent.click(resume);
 expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('未保存'));
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/recover'))).toBe(false);
});

it('returns package detail focus to its current table trigger after saving refreshes the record',async()=>{
 vi.mocked(api).mockResolvedValue([]);
 const props={pid:'p',kind:'package' as const,records:packages,batch:1,episode:1,panel:1,onPanel:()=>{},onLocation:()=>{},onSaved:()=>{},refresh:async()=>{},run:async()=>{}};
 const {rerender}=render(<Scripts {...props}/>);
 fireEvent.click(screen.getByRole('button',{name:'查看第1话第1格生图包'}));
 await screen.findByRole('dialog',{name:'第1话 · 第1格生图包'});
 rerender(<Scripts {...props} records={packages.map((r,i)=>i?r:{...r,version:2,adopted:2})}/>);
 fireEvent.click(screen.getByRole('button',{name:'关闭面板'}));
 await waitFor(()=>expect(document.activeElement).toBe(screen.getByRole('button',{name:'查看第1话第1格生图包'})));
});

it('freezes inspection policy at preview and shows bounded calls and report outcomes',async()=>{
 const inspected={...batch,payload:{count:2,inspection:'review_repair',call_limits:{images:4,vision:4}},jobs:batch.jobs.map((job,i)=>i?job:{...job,payload:{...job.payload,postprocess:{status:'completed',needs_manual:true,plan:{policy:'review_repair',basis:{provider:{model:'vision-fixed'},context:[],sources:[],review_skills:[]}},final_job_id:'repair'}},inspection:{id:'v1',status:'completed',report:{summary:'剧情动作偏差',issues:[{severity:'critical',category:'story',description:'应递出密信',evidence:'图1手上无密信'}]}}})};
 vi.mocked(api).mockImplementation(async(path,opts)=>path.endsWith('/documents')?[]:opts?.method?inspected:{items:[],next_start:null,total:0});
 render(<ImageBatches pid="p" packages={packages} records={packages} refresh={async()=>{}} onClose={()=>{}}/>);
 const choice=screen.getByRole('combobox',{name:'本批检查与返修'});fireEvent.keyDown(choice,{key:'Enter'});fireEvent.keyDown(choice,{key:'End'});fireEvent.keyDown(choice,{key:'Enter'});
 fireEvent.click(screen.getByRole('button',{name:'预览所选2格'}));
 expect(await screen.findByText(/业务图像调用最多4次.*视觉调用最多4次/)).toBeTruthy();
 expect(screen.getByText('剧情动作偏差')).toBeTruthy();expect(screen.getByText(/应递出密信/)).toBeTruthy();expect(screen.getByText(/仍需人工核对问题/)).toBeTruthy();
 const submission=vi.mocked(api).mock.calls.find(([,opts])=>opts?.method==='POST');expect(JSON.parse(String(submission?.[1]?.body)).inspection).toBe('review_repair');
});

it('pauses without draft gating, shows the saved clock and requires explicit continuation',async()=>{
 const paused={...batch,status:'paused',runtime:{effective_seconds:20,confirmed_seconds:20,uncertain_seconds:0,remaining_seconds:25180,target_seconds:14400,hard_limit_seconds:25200,target_reached:false,checkpoint:{reason:'paused',jobs:[]}}};
 const running={...paused,status:'running'};
 vi.mocked(api).mockImplementation(async(path,opts)=>path.endsWith('/pause')?paused:path.endsWith('/start')?running:opts?.method?batch:path.endsWith('/b')?running:{items:[],next_start:null,total:0});
 render(<ImageBatches pid="p" packages={packages} records={packages} refresh={async()=>{}} onClose={()=>{}}/>);
 fireEvent.click(screen.getByRole('button',{name:'预览所选2格'}));await screen.findByRole('button',{name:'确认并连续生成2格'});
 fireEvent.click(screen.getByLabelText('已核对本批全部输入，授权逐格调用图像模型；费用未知。'));const start=screen.getByRole('button',{name:'确认并连续生成2格'});await waitFor(()=>expect(start).toHaveProperty('disabled',false));fireEvent.click(start);
 const pause=await screen.findByRole('button',{name:'暂停新派发'});await waitFor(()=>expect(pause).toHaveProperty('disabled',false));
 localStorage.setItem('comic-draft:p:p1','pending');fireEvent.click(pause);
 expect(await screen.findByText('已暂停，等待明确继续')).toBeTruthy();expect(screen.getByText(/00:00:20/)).toBeTruthy();
 expect(screen.getByRole('button',{name:'明确恢复原批次'})).toHaveProperty('disabled',true);
 expect(vi.mocked(api).mock.calls.some(([path])=>path.endsWith('/pause'))).toBe(true);
});

it('shows uncertain time as an upper bound and offers no recovery after the hard limit',async()=>{
 const exhausted={...batch,status:'budget_exhausted',runtime:{effective_seconds:25200,confirmed_seconds:10,uncertain_seconds:25190,remaining_seconds:0,target_seconds:14400,hard_limit_seconds:25200,target_reached:true,checkpoint:{reason:'budget_exhausted',jobs:[]}}};
 vi.mocked(api).mockImplementation(async(_path,opts)=>opts?.method?exhausted:{items:[],next_start:null,total:0});
 render(<ImageBatches pid="p" packages={packages} records={packages} refresh={async()=>{}} onClose={()=>{}}/>);
 fireEvent.click(screen.getByRole('button',{name:'预览所选2格'}));expect(await screen.findByText('已达有效运行硬限')).toBeTruthy();
 expect(screen.getByText(/不是实测工作时间/)).toBeTruthy();expect(screen.queryByRole('button',{name:'明确恢复原批次'})).toBeNull();
});

it('keeps observing already submitted work after the batch reaches its hard limit',async()=>{
 const limited={...batch,status:'budget_exhausted',jobs:batch.jobs.map((j,i)=>i?j:{...j,status:'running',call:{...j.call,status:'submitting'}})};
 const finished={...limited,jobs:limited.jobs.map((j,i)=>i?j:{...j,status:'succeeded',call:{...j.call,status:'completed'},output_id:'saved-after-limit'})};
 vi.mocked(api).mockImplementation(async(path,opts)=>opts?.method?limited:path.endsWith('/b')?finished:{items:[],next_start:null,total:0});
 render(<ImageBatches pid="p" packages={packages} records={packages} refresh={async()=>{}} onClose={()=>{}}/>);
 fireEvent.click(screen.getByRole('button',{name:'预览所选2格'}));await screen.findByText('已达有效运行硬限');
 expect(await screen.findByText('候选已保存',{}, {timeout:2000})).toBeTruthy();
});

it('requires a fresh authorization after leaving an unsubmitted preview',async()=>{
 vi.mocked(api).mockImplementation(async(_path,opts)=>opts?.method?batch:{items:[],next_start:null,total:0});
 render(<ImageBatches pid="p" packages={packages} records={packages} refresh={async()=>{}} onClose={()=>{}}/>);
 fireEvent.click(screen.getByRole('button',{name:'预览所选2格'}));await screen.findByRole('button',{name:'确认并连续生成2格'});
 fireEvent.click(screen.getByLabelText('已核对本批全部输入，授权逐格调用图像模型；费用未知。'));
 await waitFor(()=>expect(screen.getByRole('button',{name:'确认并连续生成2格'})).toHaveProperty('disabled',false));
 fireEvent.click(screen.getByRole('button',{name:'查看所选包的新预览'}));
 fireEvent.click(screen.getByRole('button',{name:'预览所选2格'}));
 const start=await screen.findByRole('button',{name:'确认并连续生成2格'});
 expect(start).toHaveProperty('disabled',true);
 expect(screen.getByLabelText('已核对本批全部输入，授权逐格调用图像模型；费用未知。')).toHaveProperty('checked',false);
 expect(vi.mocked(api).mock.calls.some(([path])=>path.endsWith('/start'))).toBe(false);
 expect(screen.getByText(/并发受共享运行容量设置约束/)).toBeTruthy();
});
