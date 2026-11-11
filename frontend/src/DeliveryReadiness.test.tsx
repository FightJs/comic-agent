// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {DeliveryReadiness} from './DeliveryReadiness';
import {api} from './api';
vi.mock('./api',async()=>({...await vi.importActual('./api'),api:vi.fn()}));
HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
afterEach(()=>{cleanup();vi.resetAllMocks();});
const result:any={status:'blocked',scope:{episode:2,batch:null},summary:{source_panels:1,ready_panels:0,blocked_panels:1},pixel_bytes_reverified:false,panels:[{episode:2,panel:3,script:{id:'script-a',version:1,source:'mock'},images:[],vision:null,blockers:['missing_image','unobserved']}]};
it('loads only on explicit click and shows source range, mock and per-panel blockers',async()=>{
 vi.mocked(api).mockResolvedValue(result);render(<DeliveryReadiness pid="p" scope="episode" episode={2} batch={1}/>);
 expect(api).not.toHaveBeenCalled();expect(screen.queryByRole('dialog')).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'核对交付完整性'}));
 expect(await screen.findByText(/缺图/)).toBeTruthy();expect(screen.getByText(/未观察/)).toBeTruthy();expect(screen.getByText(/模拟来源/)).toBeTruthy();
 expect(api).toHaveBeenCalledWith('/projects/p/delivery-readiness?episode=2');expect(screen.getByText(/第2话 · 第3格/)).toBeTruthy();
});
it('keeps failed refresh results tagged as previous data and separates changed scope',async()=>{
 vi.mocked(api).mockResolvedValueOnce(result);const view=render(<DeliveryReadiness pid="p" scope="episode" episode={2} batch={1}/>);
 fireEvent.click(screen.getByRole('button',{name:'核对交付完整性'}));await screen.findByText(/缺图/);
 view.rerender(<DeliveryReadiness pid="p" scope="episode" episode={4} batch={1}/>);
 expect(screen.getByText(/上次数据：第2话/)).toBeTruthy();expect(api).toHaveBeenCalledTimes(1);
 vi.mocked(api).mockRejectedValueOnce(new Error('服务不可用'));fireEvent.click(screen.getByRole('button',{name:'重新核对当前范围'}));
 expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('服务不可用'));expect(screen.getByText(/缺图/)).toBeTruthy();expect(screen.getByText(/上次数据：第2话/)).toBeTruthy();
});
it('never describes a ready database snapshot as complete production',async()=>{
 vi.mocked(api).mockResolvedValue({...result,status:'ready',panels:[],summary:{source_panels:1,ready_panels:1,blocked_panels:0}});
 render(<DeliveryReadiness pid="p" scope="batch" episode={2} batch={3}/>);fireEvent.click(screen.getByRole('button',{name:'核对交付完整性'}));
 expect(await screen.findByText(/数据库证据未发现阻断/)).toBeTruthy();expect(screen.getByText(/像素文件未重新复核/)).toBeTruthy();
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/projects/p/delivery-readiness?batch=3'));
});
it('labels a late response with its requested range after navigation and does not auto-fetch',async()=>{
 let finish!:(value:any)=>void;vi.mocked(api).mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
 const view=render(<DeliveryReadiness pid="p" scope="episode" episode={2} batch={1}/>);
 fireEvent.click(screen.getByRole('button',{name:'核对交付完整性'}));view.rerender(<DeliveryReadiness pid="p" scope="batch" episode={12} batch={2}/>);
 finish(result);expect(await screen.findByText(/上次数据：第2话/)).toBeTruthy();expect(screen.getByText(/当前核对范围：第2批/)).toBeTruthy();expect(api).toHaveBeenCalledTimes(1);
});
it('shows an empty source range as undetermined',async()=>{
 vi.mocked(api).mockResolvedValue({...result,status:'empty_scope',panels:[],summary:{source_panels:0,ready_panels:0,blocked_panels:0}});
 render(<DeliveryReadiness pid="p" scope="episode" episode={2} batch={1}/>);fireEvent.click(screen.getByRole('button',{name:'核对交付完整性'}));
 expect(await screen.findByText(/没有当前有效源脚本，无法判定/)).toBeTruthy();
});
