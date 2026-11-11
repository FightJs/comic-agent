// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {DocumentGeneration} from './DocumentGeneration';
import {api} from './api';
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:vi.fn(async(url:string)=>url.includes('/tasks')?[]:{ids:['task']})}));
HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
afterEach(()=>{cleanup();localStorage.clear();vi.clearAllMocks();});
const skeleton={id:'s',project_id:'p',kind:'skeleton',title:'固定骨架',version:2,adopted:2,content:{html:'<p>骨架</p>'}} as any;
it('submits document generation with the visibly selected skeleton version',async()=>{
 render(<DocumentGeneration pid="p" kind="outline" records={[skeleton]} refresh={vi.fn()} onClose={vi.fn()}/>);
 expect(screen.getByRole('combobox',{name:'参考骨架'}).textContent).toContain('固定骨架 · v2');
 fireEvent.change(screen.getByRole('textbox',{name:'本次生成要求'}),{target:{value:'每话突出转折'}});
 fireEvent.click(screen.getByRole('button',{name:'生成细纲候选'}));
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([url])=>url.endsWith('/production-jobs'))).toBe(true));
 const request=vi.mocked(api).mock.calls.find(([url])=>url.endsWith('/production-jobs'))!;
 expect(JSON.parse(request[1]!.body as string)).toMatchObject({operation:'document',document_kind:'outline',basis:[{id:'s',version:2}],instruction:'每话突出转折'});
});
it('retains requirements and blocks generation from an unsaved reference',async()=>{
 localStorage.setItem('comic-draft:p:s','unsaved');
 render(<DocumentGeneration pid="p" kind="outline" records={[skeleton]} refresh={vi.fn()} onClose={vi.fn()}/>);
 fireEvent.change(screen.getByRole('textbox',{name:'本次生成要求'}),{target:{value:'保留动机'}});
 fireEvent.click(screen.getByRole('button',{name:'生成细纲候选'}));
 expect(await screen.findByText(/参考或目标仍有未保存草稿/)).toBeTruthy();
 expect((screen.getByRole('textbox',{name:'本次生成要求'}) as HTMLTextAreaElement).value).toBe('保留动机');
 expect(vi.mocked(api).mock.calls.some(([url])=>url.endsWith('/production-jobs'))).toBe(false);
});
