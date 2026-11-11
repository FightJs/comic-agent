// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {PauseToCheckpoint} from './PauseToCheckpoint';
import {api} from './api';
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
it('requests a pause without cancelling and keeps the pending state until the parent settles',async()=>{
 vi.mocked(api).mockResolvedValue({status:'running',pause_requested:true});const changed=vi.fn();
 render(<PauseToCheckpoint endpoint="/projects/p/agent/runs/r/pause" requested={false} focusId="checkpoint" onChanged={changed}/>);
 fireEvent.click(screen.getByRole('button',{name:'暂停到检查点'}));
 await waitFor(()=>expect(changed).toHaveBeenCalledOnce());
 expect(api).toHaveBeenCalledWith('/projects/p/agent/runs/r/pause',expect.objectContaining({body:'{}'}));
 expect(screen.getByRole('button',{name:'正在暂停，等待收尾'}).hasAttribute('disabled')).toBe(true);
 expect(screen.getByRole('status').textContent).toContain('不表示已经暂停');
});
it('restores a persisted pending intent without issuing another request',()=>{
 render(<PauseToCheckpoint endpoint="/pause" requested focusId="checkpoint" onChanged={vi.fn()}/>);
 expect(screen.getByRole('button',{name:'正在暂停，等待收尾'}).hasAttribute('disabled')).toBe(true);
 expect(api).not.toHaveBeenCalled();
});
it('retains the retry action and puts a failed pause message beside the control',async()=>{
 vi.mocked(api).mockRejectedValue(Error('运行层暂不可确认'));
 render(<PauseToCheckpoint endpoint="/pause" requested={false} focusId="checkpoint" onChanged={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'暂停到检查点'}));
 expect(await screen.findByRole('alert')).toHaveProperty('textContent','运行层暂不可确认');
 expect(screen.getByRole('button',{name:'暂停到检查点'}).hasAttribute('disabled')).toBe(false);
});
it('returns keyboard focus to the unchecked continuation grant after the active control disappears',async()=>{
 vi.mocked(api).mockResolvedValue({pause_requested:true});
 const view=render(<><PauseToCheckpoint endpoint="/pause" requested={false} focusId="checkpoint" onChanged={vi.fn()}/><section id="checkpoint"><input aria-label="后续授权" type="checkbox"/></section></>);
 fireEvent.click(screen.getByRole('button',{name:'暂停到检查点'}));
 await screen.findByRole('button',{name:'正在暂停，等待收尾'});
 view.rerender(<section id="checkpoint"><input aria-label="后续授权" type="checkbox"/></section>);
 await waitFor(()=>expect(document.activeElement).toBe(screen.getByRole('checkbox',{name:'后续授权'})));
 expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false);
});
