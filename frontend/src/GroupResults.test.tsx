// @vitest-environment jsdom
import {cleanup,render,screen,fireEvent,within} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {GroupResults} from './Workflow';
import {primaryRecord} from './workflowLogic';
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:vi.fn(async(url:string)=>url.includes('/tasks')?[{id:'task',status:'succeeded',output_id:'a',payload:{operation:'range',episode:2,panel:1,output_ids:['a','b'],group_id:'g',instruction:'逐格'}}]:{id:url.split('?')[0].endsWith('a')?'a':'b',kind:'script',version:1,source:'ai',content:{creation_candidate:true,episode:2,panel:url.split('?')[0].endsWith('a')?1:2,description:url.split('?')[0].endsWith('a')?'第一格完整描述':'第二格完整描述'}})}));
HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
afterEach(cleanup);
it('shows every generated panel and its content before explicit adoption',async()=>{
 render(<GroupResults pid="p" groups={['g']} refresh={vi.fn()} onClose={vi.fn()}/>);
 expect(await screen.findByText('第一格完整描述')).toBeTruthy();
 expect(await screen.findByText('第二格完整描述')).toBeTruthy();
 expect(screen.getAllByRole('button',{name:'采用此格候选'})).toHaveLength(2);
});
it('keeps unadopted first results out of primary production rows',()=>{
 expect(primaryRecord({content:{creation_candidate:true}})).toBe(false);
 expect(primaryRecord({content:{}})).toBe(true);
});

it('compares a first package to its source script instead of an empty old prompt',async()=>{
 const {api}=await import('./api');
 vi.mocked(api).mockImplementation(async(url:string)=>url.includes('/tasks')?[{id:'pkg-task',status:'succeeded',output_id:'pkg',payload:{operation:'package',episode:2,panel:1,group_id:'g',snapshots:[{id:'script',kind:'script',version:2,content:{description:'源脚本画面正文'}}]}}]:{id:'pkg',kind:'package',version:1,source:'ai',content:{creation_candidate:true,prompt:'新完整提示词',shot_prompt:'新分镜段'}});
 render(<GroupResults pid="p" groups={['g']} refresh={vi.fn()} onClose={vi.fn()}/>);
 expect(await screen.findByText('源脚本 v2')).toBeTruthy();
 expect(screen.getByText('源脚本画面正文')).toBeTruthy();
 expect(screen.getByText('新分镜段')).toBeTruthy();
 expect(screen.getByText('新完整提示词')).toBeTruthy();
});

it('shows adoption conflicts next to the affected panel in long results',async()=>{
 const {api}=await import('./api');
 vi.mocked(api).mockImplementation(async(url:string)=>{
   if(url.endsWith('/adopt'))throw Error('原稿已有新版本，候选保留');
   return url.includes('/tasks')?[{id:'task',status:'succeeded',output_id:'out',payload:{operation:'rewrite',episode:2,panel:1,group_id:'g',snapshots:[]}}]:{id:'out',kind:'script',version:1,source:'ai',content:{candidate_for:'old',description:'候选正文'}};
 });
 render(<GroupResults pid="p" groups={['g']} refresh={vi.fn()} onClose={vi.fn()}/>);
 const button=await screen.findByRole('button',{name:'采用此格候选'});
 fireEvent.click(button);
 expect(await within(button.closest('.group-result') as HTMLElement).findByText('原稿已有新版本，候选保留')).toBeTruthy();
});

it('keeps the generated version visible after the adopted record is edited later',async()=>{
 const {api}=await import('./api');
 vi.mocked(api).mockImplementation(async(url:string)=>{
   if(url.includes('/tasks'))return [{id:'task',status:'succeeded',output_id:'out',payload:{operation:'range',episode:2,panel:1,group_id:'g',output_versions:{out:1}}}];
   if(url.includes('?version=1'))return {id:'out',kind:'script',version:1,source:'ai',content:{creation_candidate:true,description:'冻结生成正文'}};
   return {id:'out',kind:'script',version:3,adopted:2,source:'manual',content:{description:'后续人工改稿'}};
 });
 render(<GroupResults pid="p" groups={['g']} refresh={vi.fn()} onClose={vi.fn()}/>);
 expect(await screen.findByText('冻结生成正文')).toBeTruthy();
 expect(screen.queryByText('后续人工改稿')).toBeNull();
 expect(screen.getByRole('button',{name:'此格已采用'}).hasAttribute('disabled')).toBe(true);
});

it('renders document candidates as readable text with document-specific history labels',async()=>{
 const {api}=await import('./api');
 vi.mocked(api).mockImplementation(async(url:string)=>url.includes('/tasks')?[{id:'doc-task',status:'succeeded',output_id:'doc',payload:{operation:'document',kind:'skeleton',document_kind:'skeleton',output_versions:{doc:1}}}]:{id:'doc',kind:'skeleton',version:1,source:'ai',content:{creation_candidate:true,html:'<h2>整体主线</h2><p>骨架主线正文&lt;script&gt;</p>'}});
 render(<GroupResults pid="p" kindFilter="skeleton" refresh={vi.fn()} onClose={vi.fn()}/>);
 expect(await screen.findByText(/骨架主线正文<script>/)).toBeTruthy();
 expect(screen.getByRole('heading',{name:/全书骨架/})).toBeTruthy();
 expect(screen.getByRole('button',{name:'采用文档候选'})).toBeTruthy();
 expect(document.querySelector('.candidate-text script')).toBeNull();
});

it('shows text-only legacy documents as the original side of a candidate comparison',async()=>{
 const {api}=await import('./api');
 vi.mocked(api).mockImplementation(async(url:string)=>url.includes('/tasks')?[{id:'doc-task',status:'succeeded',output_id:'doc',payload:{operation:'document',kind:'skeleton',document_kind:'skeleton',snapshots:[{kind:'skeleton',version:1,content:{text:'旧版纯文本骨架'}}]}}]:{id:'doc',kind:'skeleton',version:1,source:'ai',content:{candidate_for:'old',html:'<p>新候选骨架</p>'}});
 render(<GroupResults pid="p" kindFilter="skeleton" refresh={vi.fn()} onClose={vi.fn()}/>);
 expect(await screen.findByText('旧版纯文本骨架')).toBeTruthy();
 expect(screen.getByText('新候选骨架')).toBeTruthy();
});
it('uses the text production pause endpoint and restores its pending intent from task state',async()=>{
 const {api}=await import('./api');let requested=false;
 vi.mocked(api).mockImplementation(async(url:string)=>{
  if(url.endsWith('/pause')){requested=true;return {id:'manual-job',status:'running',pause_requested:true};}
  if(url.includes('/tasks'))return [{id:'manual-job',status:'running',pause_requested:requested,output_id:null,payload:{operation:'rewrite',episode:2,panel:1,group_id:'g',frozen:{stage:'script'},source:'ai'}}];
  throw Error(url);
 });
 render(<GroupResults pid="p" groups={['g']} refresh={vi.fn()} onClose={vi.fn()}/>);
 fireEvent.click(await screen.findByRole('button',{name:'暂停到检查点'}));
 expect(await screen.findByRole('button',{name:'正在暂停，等待收尾'})).toBeTruthy();
 expect(screen.getByRole('button',{name:'取消此任务'}).hasAttribute('disabled')).toBe(false);
 expect(vi.mocked(api).mock.calls.some(([url])=>url==='/projects/p/production-jobs/manual-job/pause')).toBe(true);
 expect(vi.mocked(api).mock.calls.some(([url])=>url.endsWith('/cancel'))).toBe(false);
});
