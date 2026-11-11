// @vitest-environment jsdom
import {cleanup,render,screen,fireEvent,waitFor} from '@testing-library/react';
import {afterEach,it,expect,vi} from 'vitest';
import {AgentStyleTest} from './AgentStyleTest';
import {api} from './api';
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:vi.fn()}));
vi.mock('./ImageGeneration',()=>({ImageGeneration:({jobId,onClose}:any)=><div><p>原图像任务 {jobId}</p><button onClick={onClose}>关闭测试图预览</button></div>}));
afterEach(()=>{cleanup();localStorage.clear();vi.resetAllMocks();});
const summary={id:'group',title:'归乡三套',source:'ai'};
const detail={...summary,stale:false,test:{representative:{character:'林秋',appearance:'深色外套',scene:'故乡街头',setting:'雨夜街灯',action:'接过密信'},basis:{outline:{id:'outline',title:'已审细纲',version:2},sources:[{record_id:'novel',title:'合成原著',start:0,end:12,quote:'林秋在故乡街头接过密信。'}]}},plans:['A','B','C'].map((option,index)=>({id:'plan'+option,job_id:null,source:'ai',status:'pending',plan:{prompt:'固定板提示词'+option,style_test:{option,features:{name:'方向'+option,line:'线条'+index,proportions:'自然比例',color:'克制配色',shadow:'平涂'}}}}))};
it('shows three comparable directions and opens only the explicitly chosen preview',async()=>{
 let saved=false;
 vi.mocked(api).mockImplementation(async path=>{if(path.endsWith('/preview')){saved=true;return {id:'jobA'};}return saved?{...detail,plans:detail.plans.map(p=>p.id==='planA'?{...p,job_id:'jobA'}:p)}:detail;});
 const view=render(<AgentStyleTest pid="p" summary={summary} runStatus="running" records={[]} onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'查看三套画风方案'}));
 expect(await screen.findByText('林秋')).toBeTruthy();expect(screen.getAllByRole('heading',{level:5})).toHaveLength(3);
 expect((screen.getByRole('button',{name:'预览方案 A'}) as HTMLButtonElement).disabled).toBe(true);
 view.rerender(<AgentStyleTest pid="p" summary={summary} runStatus="completed" records={[]} onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'预览方案 A'}));
 expect(await screen.findByText('原图像任务 jobA')).toBeTruthy();
 const close=screen.getByRole('button',{name:'关闭测试图预览'});close.focus();fireEvent.click(close);
 await waitFor(()=>expect(document.activeElement).toBe(screen.getByRole('button',{name:'查看方案 A 的图像任务'})));
 expect(vi.mocked(api).mock.calls.some(([url])=>url.endsWith('/start'))).toBe(false);
 expect(vi.mocked(api).mock.calls.filter(([,options])=>options?.method==='POST')).toHaveLength(1);
});
it('preserves fixed evidence on conflict and blocks preview over unsaved source drafts',async()=>{
 vi.mocked(api).mockResolvedValue(detail);
 render(<AgentStyleTest pid="p" summary={summary} runStatus="completed" records={[]} onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'查看三套画风方案'}));await screen.findByText('林秋');
 localStorage.setItem('comic-draft:p:outline','unsaved');fireEvent.click(screen.getByRole('button',{name:'预览方案 B'}));
 expect(await screen.findByText(/未保存草稿/)).toBeTruthy();expect(vi.mocked(api).mock.calls).toHaveLength(1);
 localStorage.clear();vi.mocked(api).mockRejectedValueOnce(Error('画风测试依据已变化'));
 fireEvent.click(screen.getByRole('button',{name:'预览方案 B'}));expect(await screen.findByText('画风测试依据已变化')).toBeTruthy();expect(screen.getByText('林秋')).toBeTruthy();
});
it('shows actual returns for comparison and keeps stale tasks accessible for original-result recovery',async()=>{
 const group={...detail,stale:true,plans:detail.plans.map(p=>({...p,job_id:'job'+p.id,job:{id:'job'+p.id,status:'succeeded',call:{result:{url:'/api/files/'+p.id}}}}))};
 vi.mocked(api).mockResolvedValue(group);
 render(<AgentStyleTest pid="p" summary={summary} runStatus="completed" records={[]} onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'查看三套画风方案'}));
 expect(await screen.findAllByRole('img')).toHaveLength(3);
 expect(screen.getByText(/固定依据已变化/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'查看方案 C 的图像任务'}));
 expect(await screen.findByText('原图像任务 jobplanC')).toBeTruthy();
 expect(vi.mocked(api).mock.calls).toHaveLength(1);
});

it('distinguishes adopted and rejected returns when reopening comparison',async()=>{
 const group={...detail,plans:detail.plans.map((p,index)=>({...p,job_id:'job'+p.id,job:{status:'succeeded',call:{result:{url:'/api/files/'+p.id}},output:{id:p.id,adopted:index===0?2:0,review:'pending',content:index===0?{url:'/api/files/'+p.id}:{creation_candidate:true,rejected:true}}}}))};
 vi.mocked(api).mockResolvedValue(group);
 render(<AgentStyleTest pid="p" summary={summary} runStatus="completed" records={[]} onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'查看三套画风方案'}));
 expect(await screen.findByText('已采用 · 待审核；画风确认仍须另行完成')).toBeTruthy();
 expect(screen.getAllByText('图片候选已拒绝')).toHaveLength(2);
});

it('does not claim the original test return is adopted after another image replaces it',async()=>{
 const group={...detail,plans:detail.plans.map(p=>({...p,job_id:'job'+p.id,job:{status:'succeeded',call:{result:{url:'/api/files/original'}},output:{id:p.id,adopted:3,review:'pending',content:{url:'/api/files/replacement'}}}}))};
 vi.mocked(api).mockResolvedValue(group);
 render(<AgentStyleTest pid="p" summary={summary} runStatus="completed" records={[]} onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'查看三套画风方案'}));
 expect(await screen.findAllByText('原测试图已被新版本替换；此处保留原返回')).toHaveLength(3);
 expect(screen.queryByText('已采用 · 待审核；画风确认仍须另行完成')).toBeNull();
});

it('prepares the trio only on request and never submits a start authorization during preview',async()=>{
 let prepared=false;
 vi.mocked(api).mockImplementation(async path=>{if(path.endsWith('/batch-preview')){prepared=true;return {id:'batch'};}return prepared?{...detail,batch:{id:'batch',status:'preview',payload:{mode:'style_tests',count:3,call_limits:{images:3,vision:0}},runtime:{effective_seconds:0,remaining_seconds:25200,uncertain_seconds:0},jobs:detail.plans.map(p=>({id:p.id,call:{manifest:{provider:{model:'fixture-image'},parameters:{size:'1024x1536'}},status:'prepared'}}))}}:detail;});
 render(<AgentStyleTest pid="p" summary={summary} runStatus="completed" records={[]} onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'查看三套画风方案'}));await screen.findByText('林秋');
 expect(vi.mocked(api).mock.calls.filter(([,o])=>o?.method==='POST')).toHaveLength(0);
 fireEvent.click(screen.getByRole('button',{name:'预览整组三张'}));
 expect(await screen.findByRole('button',{name:'确认并连续生成三张'})).toBeTruthy();
 expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false);
 expect(vi.mocked(api).mock.calls.some(([url])=>url.endsWith('/start'))).toBe(false);
});
it('fixes the chosen retry policy before preparing the three image previews',async()=>{
 vi.mocked(api).mockResolvedValue(detail);
 render(<AgentStyleTest pid="p" summary={summary} runStatus="completed" records={[]} onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'查看三套画风方案'}));await screen.findByText('林秋');
 const selector=screen.getByRole('combobox',{name:'未发出时额外技术重试次数'});fireEvent.keyDown(selector,{key:'Home'});
 for(let i=0;i<3;i++)fireEvent.keyDown(selector,{key:'ArrowDown'});fireEvent.keyDown(selector,{key:'Enter'});
 fireEvent.click(screen.getByRole('button',{name:'预览整组三张'}));
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([url])=>url.endsWith('/batch-preview'))).toBe(true));
 const posted=vi.mocked(api).mock.calls.find(([url])=>url.endsWith('/batch-preview'));
 expect(JSON.parse(String(posted?.[1]?.body))).toEqual({max_not_sent_retries:3});
 expect(vi.mocked(api).mock.calls.some(([url])=>url.endsWith('/start'))).toBe(false);
});
