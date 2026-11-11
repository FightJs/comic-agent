// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {api,ApiError} from './api';
import {ToolReceiptRecovery} from './ToolReceiptRecovery';
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
const report={read_only:true,recovery_available:true,recovery:null,receipts:[{call_id:'c',name:'query',state:'matched',host_saved:true,node_status:'pending'}]};
it('reads only on request and requires a separate unchecked result-only grant',async()=>{
 vi.mocked(api).mockResolvedValue(report);const changed=vi.fn();
 render(<ToolReceiptRecovery endpoint="/run" expectedVersion={3} onChanged={changed}/>);
 expect(api).not.toHaveBeenCalled();fireEvent.click(screen.getByRole('button',{name:'核对工具回执'}));
 const grant=await screen.findByRole('checkbox');expect((grant as HTMLInputElement).checked).toBe(false);
 expect(screen.getByText(/不代表业务成功/)).toBeTruthy();
 fireEvent.click(grant);fireEvent.click(screen.getByRole('button',{name:'明确仅补回已保存结果'}));
 await waitFor(()=>expect(changed).toHaveBeenCalledOnce());
 expect(api).toHaveBeenCalledWith('/run/recover-tools',expect.objectContaining({body:'{"confirm":true,"expected_version":3}'}));
 expect(vi.mocked(api).mock.calls).toHaveLength(2);
});
it('retains the receipt and grant on conflict without continuing',async()=>{
 vi.mocked(api).mockResolvedValueOnce(report).mockRejectedValueOnce(new ApiError(409,'输入已变化'));
 render(<ToolReceiptRecovery endpoint="/attempt" onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button'));fireEvent.click(await screen.findByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'明确仅补回已保存结果'}));
 expect((await screen.findByRole('alert')).textContent).toContain('核对记录与当前输入已保留');
 expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(true);
});
it('does not offer recovery when evidence cannot authorize it',async()=>{
 vi.mocked(api).mockResolvedValue({...report,recovery_available:false});render(<ToolReceiptRecovery endpoint="/run" onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button'));expect(await screen.findByText(/缺少可恢复证据/)).toBeTruthy();expect(screen.queryByRole('checkbox')).toBeNull();
});
it('ignores an old read after the target changes and ignores recovery after unmount',async()=>{
 let resolve!:(value:any)=>void;vi.mocked(api).mockImplementationOnce(()=>new Promise(r=>{resolve=r;}));const changed=vi.fn();
 const view=render(<ToolReceiptRecovery endpoint="/old" onChanged={changed}/>);fireEvent.click(screen.getByRole('button'));
 view.rerender(<ToolReceiptRecovery endpoint="/new" onChanged={changed}/>);resolve(report);
 await waitFor(()=>expect(screen.getByRole('button').hasAttribute('disabled')).toBe(false));expect(screen.queryByRole('checkbox')).toBeNull();
 vi.mocked(api).mockResolvedValueOnce(report);fireEvent.click(screen.getByRole('button'));fireEvent.click(await screen.findByRole('checkbox'));
 vi.mocked(api).mockImplementationOnce(()=>new Promise(r=>{resolve=r;}));fireEvent.click(screen.getByRole('button',{name:'明确仅补回已保存结果'}));view.unmount();resolve({});await Promise.resolve();expect(changed).not.toHaveBeenCalled();
});
it('shows each real ledger discrepancy and node disposition in Chinese',async()=>{
 vi.mocked(api).mockResolvedValue({...report,receipts:[
  {call_id:'1',name:'查询一',state:'host_saved_node_unconfirmed',host_saved:true,node_status:'registered'},
  {call_id:'2',name:'查询二',state:'missing_or_legacy',host_saved:false,node_status:null},
  {call_id:'3',name:'查询三',state:'mismatch',host_saved:true,node_status:'received'},
  {call_id:'4',name:'查询四',state:'unverified',host_saved:true,node_status:'rejected'}]});
 render(<ToolReceiptRecovery endpoint="/run" onChanged={vi.fn()}/>);fireEvent.click(screen.getByRole('button'));
 expect(await screen.findByText(/宿主已保存，运行端尚未确认/)).toBeTruthy();
 for(const message of ['缺少对应记录或旧记录证据不足','调用身份、输入或结果摘要不一致','证据不足，尚未验证','已登记，尚未确认返回','无对应运行记录','运行端已接收','运行端已拒绝'])expect(screen.getByText(new RegExp(message))).toBeTruthy();
});
it('lets the user explicitly end a failed recovery after a 503 and stale retry',async()=>{
 const changed=vi.fn();vi.mocked(api).mockResolvedValueOnce(report).mockRejectedValueOnce(new ApiError(503,'恢复服务不可用')).mockRejectedValueOnce(new ApiError(409,'输入已变化')).mockResolvedValueOnce({status:'cancelled'});
 render(<ToolReceiptRecovery endpoint="/run" onChanged={changed}/>);
 fireEvent.click(screen.getByRole('button'));fireEvent.click(await screen.findByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'明确仅补回已保存结果'}));
 await screen.findByText('恢复服务不可用');
 expect(api).toHaveBeenCalledTimes(2);expect(changed).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'明确仅补回已保存结果'}));await screen.findByText(/输入已变化/);
 fireEvent.click(screen.getByRole('button',{name:'结束本次恢复'}));await waitFor(()=>expect(changed).toHaveBeenCalledOnce());
 expect(api).toHaveBeenLastCalledWith('/run/cancel',expect.objectContaining({body:'{}'}));
});
it.each(['pending','failed'])('reopens a %s recovery with an explicit task cancellation endpoint',async status=>{
 vi.mocked(api).mockResolvedValueOnce({...report,recovery_available:false,recovery:{recovery_id:'saved',status}}).mockResolvedValueOnce({status:'cancelled'});
 const changed=vi.fn();render(<ToolReceiptRecovery endpoint="/production-jobs/t/attempts/a" cancelEndpoint="/production-jobs/t/cancel" onChanged={changed}/>);
 fireEvent.click(screen.getByRole('button'));const cancel=await screen.findByRole('button',{name:'结束本次恢复'});
 expect(api).toHaveBeenCalledTimes(1);fireEvent.click(cancel);await waitFor(()=>expect(changed).toHaveBeenCalledOnce());
 expect(api).toHaveBeenLastCalledWith('/production-jobs/t/cancel',expect.objectContaining({body:'{}'}));
});
it('keeps the explicit cancellation exit when the same discussion version changes after a failed POST',async()=>{
 const changed=vi.fn();vi.mocked(api).mockResolvedValueOnce(report).mockRejectedValueOnce(new ApiError(503,'恢复超时')).mockResolvedValueOnce({status:'cancelled'});
 const view=render(<ToolReceiptRecovery endpoint="/run" expectedVersion={1} onChanged={changed}/>);
 fireEvent.click(screen.getByRole('button'));fireEvent.click(await screen.findByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'明确仅补回已保存结果'}));await screen.findByText('恢复超时');
 view.rerender(<ToolReceiptRecovery endpoint="/run" expectedVersion={2} onChanged={changed}/>);
 fireEvent.click(screen.getByRole('button',{name:'结束本次恢复'}));await waitFor(()=>expect(changed).toHaveBeenCalledOnce());
 expect(api).toHaveBeenLastCalledWith('/run/cancel',expect.objectContaining({body:'{}'}));
});
