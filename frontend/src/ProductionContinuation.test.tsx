// @vitest-environment jsdom
import {cleanup,render,screen,fireEvent,waitFor} from '@testing-library/react';
import {afterEach,it,expect,vi} from 'vitest';
import {ProductionContinuation} from './ProductionContinuation';
import {api} from './api';
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:vi.fn()}));
afterEach(()=>{cleanup();vi.clearAllMocks();});
const checkpoint={attempt_id:'segment',model_requests:20,model_limit:20,tool_calls:18,tool_limit:50,session_saved:true,unreturned_models:0,unresolved_tools:0};
it('requires explicit authorization and preserves the choice on a stale rejection',async()=>{
 const changed=vi.fn();vi.mocked(api).mockRejectedValueOnce(Error('输入已有新版本，未续接')).mockResolvedValueOnce({id:'task'});
 render(<ProductionContinuation pid="p" tid="task" checkpoint={checkpoint} onChanged={changed}/>);
 const button=screen.getByRole('button',{name:'明确续接此生产检查点'});
 expect(button.hasAttribute('disabled')).toBe(true);
 const consent=screen.getByRole('checkbox');fireEvent.click(consent);fireEvent.click(button);
 expect(await screen.findByText('输入已有新版本，未续接')).toBeTruthy();expect((consent as HTMLInputElement).checked).toBe(true);
 fireEvent.click(button);await waitFor(()=>expect(changed).toHaveBeenCalledTimes(1));
 expect(api).toHaveBeenCalledWith('/projects/p/production-jobs/task/attempts/segment/continue',expect.objectContaining({body:JSON.stringify({confirm:true})}));
});
it('never offers continuation for an uncertain checkpoint',()=>{
 render(<ProductionContinuation pid="p" tid="task" checkpoint={{...checkpoint,unreturned_models:1}} onChanged={vi.fn()}/>);
 expect(screen.queryByRole('checkbox')).toBeNull();expect(screen.queryByRole('button')).toBeNull();
 expect(screen.getByText(/未决调用/)).toBeTruthy();
});
it('does not carry approval to another segment',()=>{
 const {rerender}=render(<ProductionContinuation key="a" pid="p" tid="task" checkpoint={checkpoint} onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('checkbox'));
 rerender(<ProductionContinuation key="b" pid="p" tid="task" checkpoint={{...checkpoint,attempt_id:'next'}} onChanged={vi.fn()}/>);
 expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false);
});
it('describes a manual pause without claiming the model allowance was exhausted',()=>{
 render(<ProductionContinuation pid="p" tid="task" checkpoint={{...checkpoint,reason:'manual_pause',model_requests:1,tool_calls:0}} onChanged={vi.fn()}/>);
 expect(screen.getByRole('heading',{name:'已暂停，原任务与输入已保留'})).toBeTruthy();
 expect(screen.queryByText(/额度已暂停/)).toBeNull();
});
it('offers a separate receipt repair for unresolved tools and reloads without continuing',async()=>{
 const changed=vi.fn();vi.mocked(api).mockResolvedValue({receipts:[],recovery_available:true,read_only:true});
 render(<ProductionContinuation pid="p" tid="task" checkpoint={{...checkpoint,unresolved_tools:1}} onChanged={changed}/>);
 expect(api).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'核对工具回执'}));
 fireEvent.click(await screen.findByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'明确仅补回已保存结果'}));
 await waitFor(()=>expect(changed).toHaveBeenCalledOnce());
 expect(api).toHaveBeenCalledWith('/projects/p/production-jobs/task/attempts/segment/recover-tools',expect.objectContaining({body:'{"confirm":true}'}));
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/continue'))).toBe(false);
});
it('ends a persisted tool recovery through the task cancel route',async()=>{
 const changed=vi.fn();vi.mocked(api).mockResolvedValueOnce({receipts:[],recovery_available:false,recovery:{recovery_id:'r',status:'failed'},read_only:true}).mockResolvedValueOnce({status:'cancelled'});
 render(<ProductionContinuation pid="p" tid="task" checkpoint={{...checkpoint,unresolved_tools:1}} onChanged={changed}/>);
 fireEvent.click(screen.getByRole('button',{name:'核对工具回执'}));fireEvent.click(await screen.findByRole('button',{name:'结束本次恢复'}));
 await waitFor(()=>expect(changed).toHaveBeenCalledOnce());
 expect(api).toHaveBeenLastCalledWith('/projects/p/production-jobs/task/cancel',expect.objectContaining({body:'{}'}));
});
it('describes recovered tools as a paused original task without claiming allowance exhaustion',()=>{
 render(<ProductionContinuation pid="p" tid="task" checkpoint={{...checkpoint,reason:'tools_recovered',model_requests:1,tool_calls:1}} onChanged={vi.fn()}/>);
 expect(screen.getByRole('heading',{name:'结果已补回，原任务已暂停；请明确续接或结束'})).toBeTruthy();expect(screen.queryByText(/额度已暂停/)).toBeNull();
});
