// @vitest-environment jsdom
import {cleanup,render,screen,fireEvent,waitFor} from '@testing-library/react';
import {afterEach,it,expect,vi} from 'vitest';
import {AgentImagePlan} from './AgentImagePlan';
import {api} from './api';
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:vi.fn()}));
vi.mock('./ImageGeneration',()=>({ImageGeneration:({jobId,onClose}:{jobId:string;onClose:()=>void})=><div><p>打开既有图像任务 {jobId}</p><button onClick={onClose}>关闭图像预览</button></div>}));
afterEach(()=>{cleanup();localStorage.clear();vi.resetAllMocks();});
const summary={id:'plan',title:'夜景重生成',source:'ai',status:'pending'};
const detail={...summary,plan:{kind:'style',title:'夜景图',prompt:'保留线条，将画面改为夜景',target:{id:'style',title:'原画风',version:2},references:[]}};
it('shows the exact prompt and only opens a preview after the reply completes',async()=>{
 vi.mocked(api).mockImplementation(async(url)=>url.endsWith('/preview')?{id:'job'}:detail);
 const {rerender}=render(<AgentImagePlan pid="p" summary={summary} runStatus="running" records={[]} onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'查看生图方案'}));
 expect(await screen.findByText(detail.plan.prompt)).toBeTruthy();
 expect(screen.getByRole('button',{name:'创建生图预览'}).hasAttribute('disabled')).toBe(true);
 rerender(<AgentImagePlan pid="p" summary={summary} runStatus="completed" records={[]} onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'创建生图预览'}));
 expect(await screen.findByText('打开既有图像任务 job')).toBeTruthy();
 expect(vi.mocked(api).mock.calls.some(([url])=>url.endsWith('/start'))).toBe(false);
});
it('keeps a stale proposal visible and never posts a preview over unsaved target drafts',async()=>{
 vi.mocked(api).mockResolvedValue(detail);localStorage.setItem('comic-draft:p:style','draft');
 render(<AgentImagePlan pid="p" summary={summary} runStatus="completed" records={[]} onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'查看生图方案'}));await screen.findByText(detail.plan.prompt);
 fireEvent.click(screen.getByRole('button',{name:'创建生图预览'}));
 expect(await screen.findByText(/未保存草稿/)).toBeTruthy();
 expect(vi.mocked(api).mock.calls).toHaveLength(1);
 localStorage.clear();vi.mocked(api).mockRejectedValueOnce(Error('目标已变化，未创建预览'));
 fireEvent.click(screen.getByRole('button',{name:'创建生图预览'}));
 expect(await screen.findByText('目标已变化，未创建预览')).toBeTruthy();expect(screen.getByText(detail.plan.prompt)).toBeTruthy();
});

it('returns keyboard focus to the current preview button when the inner panel closes',async()=>{
 vi.mocked(api).mockImplementation(async(url)=>url.endsWith('/preview')?{id:'job'}:detail);
 render(<AgentImagePlan pid="p" summary={summary} runStatus="completed" records={[]} onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'查看生图方案'}));await screen.findByText(detail.plan.prompt);
 fireEvent.click(screen.getByRole('button',{name:'创建生图预览'}));
 const close=await screen.findByRole('button',{name:'关闭图像预览'});close.focus();fireEvent.click(close);
 await waitFor(()=>expect(document.activeElement).toBe(screen.getByRole('button',{name:'打开已有生图预览'})));
});
it('freezes a chosen retry allowance in the first preview without authorizing generation',async()=>{
 vi.mocked(api).mockImplementation(async url=>url.endsWith('/preview')?{id:'job'}:detail);
 render(<AgentImagePlan pid="p" summary={summary} runStatus="completed" records={[]} onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'查看生图方案'}));await screen.findByText(detail.plan.prompt);
 const selector=screen.getByRole('combobox',{name:'未发出时额外技术重试次数'});fireEvent.keyDown(selector,{key:'Home'});
 for(let i=0;i<2;i++)fireEvent.keyDown(selector,{key:'ArrowDown'});fireEvent.keyDown(selector,{key:'Enter'});
 fireEvent.click(screen.getByRole('button',{name:'创建生图预览'}));await screen.findByText('打开既有图像任务 job');
 const posted=vi.mocked(api).mock.calls.find(([url])=>url.endsWith('/preview'));
 expect(JSON.parse(String(posted?.[1]?.body))).toEqual({max_not_sent_retries:2});
 expect(vi.mocked(api).mock.calls.some(([url])=>url.endsWith('/start'))).toBe(false);
});
