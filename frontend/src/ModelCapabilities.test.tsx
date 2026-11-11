// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ModelCapabilities} from './ModelCapabilities';
import {api,ApiError} from './api';
vi.mock('./api',async original=>({...await original<typeof import('./api')>(),api:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();});
const report={capabilities:[{kind:'text',status:'verified',source:'mock',profile_hash:'hash',observed_at:'2026-11-07T01:00:00Z',receipt:{type:'agent_run',id:'r'},limits:['只证明文本返回，不证明质量'],reason_codes:[]},{kind:'vision',status:'stale',source:'unknown',limits:[],reason_codes:['profile_changed']}],candidates:[{kind:'generation',receipt_id:'image-receipt',label:'已保存单图返回',source:'real',observed_at:'2026-11-07T01:00:00Z'}]};
it('shows all five capabilities with honest mock, stale and missing evidence boundaries',async()=>{
 vi.mocked(api).mockResolvedValue(report);render(<ModelCapabilities pid="p"/>);
 expect(await screen.findByRole('heading',{name:'文本回复'})).toBeTruthy();
 for(const name of ['工具调用','视觉理解','图像生成','图像编辑'])expect(screen.getByRole('heading',{name})).toBeTruthy();
 expect(screen.getByText(/含模拟来源/)).toBeTruthy();expect(screen.getByText(/配置已变更/)).toBeTruthy();expect(screen.getByText(/供应商实测未确认/)).toBeTruthy();expect(screen.getAllByText('未验证').length).toBe(3);
 expect(screen.getByText(/只核对本项目已有回执，不请求模型或执行工具/)).toBeTruthy();expect(screen.queryByRole('textbox')).toBeNull();expect(api).toHaveBeenCalledOnce();
});
it('requires choosing existing evidence and a separate explicit reconciliation',async()=>{
 vi.mocked(api).mockResolvedValue(report);render(<ModelCapabilities pid="p"/>);await screen.findByRole('heading',{name:'图像生成'});
 const save=screen.getByRole('button',{name:'核对并保存结果'});expect(save.hasAttribute('disabled')).toBe(true);
 const select=screen.getByRole('combobox',{name:'图像生成已有回执'});fireEvent.keyDown(select,{key:'Home'});fireEvent.keyDown(select,{key:'End'});fireEvent.keyDown(select,{key:'Enter'});
 expect(api).toHaveBeenCalledOnce();fireEvent.click(save);
 await waitFor(()=>expect(api).toHaveBeenCalledWith('/projects/p/model-capabilities/reconcile',expect.objectContaining({body:'{"evidence":[{"kind":"generation","receipt_id":"image-receipt"}]}'})));
 expect(await screen.findByRole('status')).toHaveProperty('textContent',expect.stringContaining('核对结果已保存'));
});
it('does not read or reconcile while model configuration has unsaved drafts',async()=>{
 vi.mocked(api).mockResolvedValue(report);const view=render(<ModelCapabilities pid="p" disabled/>);
 expect(api).not.toHaveBeenCalled();expect(screen.getByText(/先保存模型配置/)).toBeTruthy();
 view.rerender(<ModelCapabilities pid="p"/>);await screen.findByRole('heading',{name:'文本回复'});expect(api).toHaveBeenCalledOnce();
 const choose=screen.getByRole('combobox',{name:'图像生成已有回执'});fireEvent.keyDown(choose,{key:'Home'});fireEvent.keyDown(choose,{key:'End'});fireEvent.keyDown(choose,{key:'Enter'});
 view.rerender(<ModelCapabilities pid="p" disabled/>);fireEvent.click(screen.getByRole('button',{name:'核对并保存结果'}));expect(api).toHaveBeenCalledOnce();
});
it('retains the previous report and selection after a conflict without automatically retrying',async()=>{
 vi.mocked(api).mockResolvedValueOnce(report).mockRejectedValueOnce(new ApiError(409,'回执与当前配置不匹配'));
 render(<ModelCapabilities pid="p"/>);await screen.findByRole('heading',{name:'图像生成'});const choose=screen.getByRole('combobox',{name:'图像生成已有回执'});fireEvent.keyDown(choose,{key:'Home'});fireEvent.keyDown(choose,{key:'End'});fireEvent.keyDown(choose,{key:'Enter'});fireEvent.click(screen.getByRole('button',{name:'核对并保存结果'}));
 expect((await screen.findByRole('alert')).textContent).toContain('回执与当前配置不匹配');expect(screen.getByText('只证明文本返回，不证明质量')).toBeTruthy();expect(choose.textContent).toContain('已保存单图返回');expect(api).toHaveBeenCalledTimes(2);
});
it('ignores results belonging to an old project',async()=>{
 let release!:(value:any)=>void;vi.mocked(api).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;})).mockResolvedValueOnce({capabilities:[],candidates:[]});
 const view=render(<ModelCapabilities pid="old"/>);view.rerender(<ModelCapabilities pid="new"/>);
 await screen.findByRole('heading',{name:'文本回复'});release(report);await Promise.resolve();
 expect(screen.queryByText('只证明文本返回，不证明质量')).toBeNull();expect(screen.queryByRole('combobox')).toBeNull();
});
it('prevents duplicate saves while reconciliation is pending',async()=>{
 let release!:(value:any)=>void;vi.mocked(api).mockResolvedValueOnce(report).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
 render(<ModelCapabilities pid="p"/>);await screen.findByRole('heading',{name:'图像生成'});const choose=screen.getByRole('combobox',{name:'图像生成已有回执'});fireEvent.keyDown(choose,{key:'Home'});fireEvent.keyDown(choose,{key:'End'});fireEvent.keyDown(choose,{key:'Enter'});const save=screen.getByRole('button',{name:'核对并保存结果'});fireEvent.click(save);fireEvent.click(save);expect(api).toHaveBeenCalledTimes(2);release(report);await screen.findByText(/核对结果已保存/);
});
it('keeps the previous report if refreshing fails and never substitutes a new model call',async()=>{
 vi.mocked(api).mockResolvedValueOnce(report).mockRejectedValueOnce(Error('读取失败'));
 render(<ModelCapabilities pid="p"/>);await screen.findByText('只证明文本返回，不证明质量');fireEvent.click(screen.getByRole('button',{name:'读取最新核对结果'}));
 expect((await screen.findByRole('alert')).textContent).toContain('读取失败');expect(screen.getByText('只证明文本返回，不证明质量')).toBeTruthy();expect(api).toHaveBeenCalledTimes(2);expect(vi.mocked(api).mock.calls.every(([,o])=>!o?.method)).toBe(true);
});
it('ignores a reconciliation response after configuration becomes disabled',async()=>{
 let release!:(value:any)=>void;vi.mocked(api).mockResolvedValueOnce(report).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
 const view=render(<ModelCapabilities pid="p"/>);await screen.findByRole('heading',{name:'图像生成'});const choose=screen.getByRole('combobox',{name:'图像生成已有回执'});fireEvent.keyDown(choose,{key:'Home'});fireEvent.keyDown(choose,{key:'End'});fireEvent.keyDown(choose,{key:'Enter'});fireEvent.click(screen.getByRole('button',{name:'核对并保存结果'}));
 view.rerender(<ModelCapabilities pid="p" disabled/>);release({...report,capabilities:[{kind:'text',status:'verified',source:'real',limits:['迟到的核对结果']}]});await Promise.resolve();expect(screen.queryByText('迟到的核对结果')).toBeNull();expect(screen.queryByText(/核对结果已保存/)).toBeNull();
});
it('translates observed limits and current reason codes without implying that mock inputs identify the supplier',async()=>{
 vi.mocked(api).mockResolvedValue({candidates:[],capabilities:[{kind:'text',status:'unverified',source:'unknown',reason_codes:['no_checked_receipt']},{kind:'tool',status:'unverified',source:'unknown',reason_codes:['tool_roundtrip_unproven']},{kind:'edit',status:'verified',source:'mock',limits:{reference_count:2,mask_observed:false,image_count:1,semantic_quality_verified:false}}]});
 render(<ModelCapabilities pid="p"/>);
 expect(await screen.findByText('图像参考数：2')).toBeTruthy();expect(screen.getByText('实图数：1')).toBeTruthy();expect(screen.getByText('未观察到蒙版')).toBeTruthy();expect(screen.getByText('语义质量未经验证')).toBeTruthy();expect(screen.getByText('尚无已保存的核对回执')).toBeTruthy();expect(screen.getByText('尚无完整工具调用与结果回传证据')).toBeTruthy();expect(screen.getByText(/不据此认定供应商为替身/)).toBeTruthy();expect(screen.queryByText(/reference_count|mask_observed|image_count|semantic_quality_verified/)).toBeNull();
});
