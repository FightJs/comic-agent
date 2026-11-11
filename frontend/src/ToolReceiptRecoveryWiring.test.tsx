// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {GroupResults} from './Workflow';
import {api} from './api';
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:vi.fn()}));
HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
afterEach(()=>{cleanup();vi.resetAllMocks();});
it('exposes an interrupted production attempt in the results and repairs without a new job',async()=>{
 let repaired=false;
 vi.mocked(api).mockImplementation(async path=>{
  if(path.endsWith('/tasks?compact=true'))return [{id:'task',status:repaired?'paused':'interrupted',payload:{operation:'document',frozen:true,kind:'outline',instruction:'原任务',...(repaired?{production_checkpoint:{attempt_id:'a',session_saved:true,unreturned_models:0,unresolved_tools:0}}:{})}}];
  if(path.endsWith('/attempts'))return [{id:'a',attempt:1,status:repaired?'paused':'interrupted',raw:'部分返回'}];
  if(path.endsWith('/tool-receipts'))return {receipts:[],recovery_available:true,read_only:true};
  if(path.endsWith('/recover-tools')){repaired=true;return {};}
  throw Error('unexpected '+path);
 });
 render(<GroupResults pid="p" refresh={vi.fn()} onClose={vi.fn()}/>);
 const summary=await screen.findByText('查看模型返回与用量');fireEvent.click(summary);fireEvent(summary.parentElement!,new Event('toggle'));
 fireEvent.click(await screen.findByRole('button',{name:'核对工具回执'}));fireEvent.click(await screen.findByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'明确仅补回已保存结果'}));
 await waitFor(()=>expect((screen.getByRole('checkbox',{name:/授权新增最多20/}) as HTMLInputElement).checked).toBe(false));
 expect(api).toHaveBeenCalledWith('/projects/p/production-jobs/task/attempts/a/recover-tools',expect.objectContaining({body:'{"confirm":true}'}));
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/continue')||p.endsWith('/production-jobs'))).toBe(false);
});
it('ends a persisted failed production recovery through its task rather than attempt',async()=>{
 let ended=false;
 vi.mocked(api).mockImplementation(async path=>{
  if(path.endsWith('/tasks?compact=true'))return [{id:'task',status:ended?'cancelled':'failed',payload:{operation:'document',frozen:true,kind:'outline',instruction:'原任务'}}];
  if(path.endsWith('/attempts'))return [{id:'a',attempt:1,status:'error',raw:'部分返回'}];
  if(path.endsWith('/tool-receipts'))return {receipts:[],recovery_available:false,recovery:{recovery_id:'r',status:'pending'},read_only:true};
  if(path==='/projects/p/production-jobs/task/cancel'){ended=true;return {status:'cancelled'};}
  throw Error('unexpected '+path);
 });
 render(<GroupResults pid="p" refresh={vi.fn()} onClose={vi.fn()}/>);
 const summary=await screen.findByText('查看模型返回与用量');fireEvent.click(summary);fireEvent(summary.parentElement!,new Event('toggle'));
 fireEvent.click(await screen.findByRole('button',{name:'核对工具回执'}));fireEvent.click(await screen.findByRole('button',{name:'结束本次恢复'}));
 await waitFor(()=>expect(ended).toBe(true));expect(api).toHaveBeenCalledWith('/projects/p/production-jobs/task/cancel',expect.objectContaining({body:'{}'}));
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/attempts/a/cancel'))).toBe(false);
});
