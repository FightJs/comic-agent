// @vitest-environment jsdom
import {cleanup,render,screen,fireEvent,waitFor} from '@testing-library/react';
import {afterEach,it,expect,vi} from 'vitest';
import {StyleBatchControls} from './StyleBatchControls';
import {api} from './api';
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
const batch={id:'batch',status:'preview',error:'',payload:{mode:'style_tests',count:3,call_limits:{images:3,vision:0}},runtime:{effective_seconds:12,remaining_seconds:25188,uncertain_seconds:0},jobs:['A','B','C'].map(id=>({id,call:{manifest:{provider:{model:'fixture-image'},parameters:{size:'1024x1536'}},status:'prepared'}}))};
it('requires an unchecked grant and submits exactly confirm true for the original batch',async()=>{
 vi.mocked(api).mockResolvedValue({});const onChanged=vi.fn(),guard=vi.fn();
 render(<StyleBatchControls pid="p" batch={batch} stale={false} guard={guard} onChanged={onChanged}/>);
 const start=screen.getByRole('button',{name:'确认并连续生成三张'});
 expect((start as HTMLButtonElement).disabled).toBe(true);expect(vi.mocked(api)).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(start);
 await waitFor(()=>expect(onChanged).toHaveBeenCalled());
 expect(vi.mocked(api).mock.calls[0]).toEqual(['/projects/p/image-batches/batch/start',expect.objectContaining({body:'{"confirm":true}'})]);
 expect(guard).toHaveBeenCalled();expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false);
});
it('keeps original preview and grant on a failed request and guards unsaved source edits',async()=>{
 const guard=vi.fn<()=>void>(()=>{throw Error('依据有未保存草稿');});vi.mocked(api).mockRejectedValue(Error('输入版本已变化'));
 const view=render(<StyleBatchControls pid="p" batch={batch} stale={false} guard={guard} onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'确认并连续生成三张'}));
 expect(await screen.findByText('依据有未保存草稿')).toBeTruthy();expect(vi.mocked(api)).not.toHaveBeenCalled();
 guard.mockImplementation(()=>{});fireEvent.click(screen.getByRole('button',{name:'确认并连续生成三张'}));
 expect(await screen.findByText('输入版本已变化')).toBeTruthy();expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(true);
 view.rerender(<StyleBatchControls pid="p" batch={batch} stale={true} guard={guard} onChanged={vi.fn()}/>);
 expect((screen.getByRole('button',{name:'确认并连续生成三张'}) as HTMLButtonElement).disabled).toBe(true);
});
it('separates pause from cancel and requires a new explicit recovery grant',async()=>{
 vi.mocked(api).mockResolvedValue({});const view=render(<StyleBatchControls pid="p" batch={{...batch,status:'running'}} stale={false} guard={vi.fn()} onChanged={vi.fn()}/>);
 screen.getByRole('button',{name:'暂停整组新派发'}).focus();fireEvent.click(screen.getByRole('button',{name:'暂停整组新派发'}));
 await waitFor(()=>expect(vi.mocked(api)).toHaveBeenCalledWith('/projects/p/image-batches/batch/pause',expect.objectContaining({body:'{}'})));
 view.rerender(<StyleBatchControls pid="p" batch={{...batch,status:'paused'}} stale={false} guard={vi.fn()} onChanged={vi.fn()}/>);
 await waitFor(()=>expect(document.activeElement).toBe(screen.getByRole('checkbox')));
 expect((screen.getByRole('button',{name:'明确继续原批次'}) as HTMLButtonElement).disabled).toBe(true);
 fireEvent.click(screen.getByRole('checkbox'));fireEvent.click(screen.getByRole('button',{name:'明确继续原批次'}));
 await waitFor(()=>expect(vi.mocked(api)).toHaveBeenCalledWith('/projects/p/image-batches/batch/recover',expect.objectContaining({body:'{"confirm":true}'})));
 expect(vi.mocked(api).mock.calls.some(([url])=>url.endsWith('/start')||url.endsWith('/cancel'))).toBe(false);
});

it('permits explicit original-return recovery after basis changes while still blocking a new start',async()=>{
 vi.mocked(api).mockResolvedValue({});
 render(<StyleBatchControls pid="p" batch={{...batch,status:'needs_attention'}} stale={true} guard={vi.fn()} onChanged={vi.fn()}/>);
 const grant=screen.getByRole('checkbox');expect((grant as HTMLInputElement).disabled).toBe(false);
 fireEvent.click(grant);fireEvent.click(screen.getByRole('button',{name:'核对并恢复原返回'}));
 await waitFor(()=>expect(vi.mocked(api)).toHaveBeenCalledWith('/projects/p/image-batches/batch/recover',expect.objectContaining({body:'{"confirm":true,"restore_only":true}'})));
});
it('keeps historical physical network limits unknown rather than inferring a retry grant',()=>{
 render(<StyleBatchControls pid="p" batch={batch} stale={false} guard={vi.fn()} onChanged={vi.fn()}/>);
 expect(screen.getByText(/历史记录未保存物理网络上限/)).toBeTruthy();
 expect(screen.queryByText(/最多3次业务生图、3次物理网络尝试/)).toBeNull();
});
