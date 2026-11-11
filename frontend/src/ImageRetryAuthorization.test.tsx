// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ImageGeneration} from './ImageGeneration';
import {ImageBatches} from './ImageBatches';
import {api} from './api';
vi.mock('./api',async()=>({...await vi.importActual('./api'),api:vi.fn()}));
HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
afterEach(()=>{cleanup();vi.resetAllMocks();localStorage.clear();});
const job={id:'j',status:'preview',payload:{title:'候选',prompt:'提示词',input_refs:{},retry_policy:{version:1,max_not_sent_retries:2}},call:{manifest:{provider:{model:'image'},parameters:{size:'1024x1536'},references:[],source:'ai'}}};
const pack={id:'pkg',project_id:'p',kind:'package',title:'第1格',version:1,content:{prompt:'提示词'}} as any;
function setRetries(n:number){const trigger=screen.getByRole('combobox',{name:'未发出时额外技术重试次数'});fireEvent.keyDown(trigger,{key:'Home'});for(let i=0;i<n;i++)fireEvent.keyDown(trigger,{key:'ArrowDown'});fireEvent.keyDown(trigger,{key:'Enter'});}
it('defaults to zero and changes the submission token when retry authorization changes after a failed preview',async()=>{
 vi.mocked(api).mockImplementation(async(_path,options)=>{if(!options?.method)return [];throw Error('预览暂不可用');});
 render(<ImageGeneration pid="p" kind="style" records={[]} refresh={vi.fn()} onClose={vi.fn()}/>);
 fireEvent.change(screen.getByLabelText('图片名称'),{target:{value:'图'}});fireEvent.change(screen.getByLabelText('完整生图提示词'),{target:{value:'提示'}});
 fireEvent.click(screen.getByRole('button',{name:'预览模型与输入'}));await screen.findByText('预览暂不可用');
 const first=JSON.parse(String(vi.mocked(api).mock.calls.find(([,o])=>o?.method)?.[1]?.body));expect(first.max_not_sent_retries).toBe(0);
 setRetries(2);fireEvent.click(screen.getByRole('button',{name:'预览模型与输入'}));await waitFor(()=>expect(vi.mocked(api).mock.calls.filter(([,o])=>o?.method)).toHaveLength(2));
 const second=JSON.parse(String(vi.mocked(api).mock.calls.filter(([,o])=>o?.method)[1][1]?.body));expect(second.max_not_sent_retries).toBe(2);expect(second.submission_id).not.toBe(first.submission_id);
});
it('shows the frozen single-image authorization and per-attempt evidence without resetting on recover',async()=>{
 const attempts={max_attempts:3,remaining_attempts:1,attempts:[{sequence:1,evidence:{outcome:'not_sent',response_started:false,transport_phase:'connect'}},{sequence:2,evidence:{outcome:'unknown',response_started:true,transport_phase:'response_body'}}]};
 vi.mocked(api).mockResolvedValue({...job,status:'interrupted',call:{...job.call,attempts}});
 render(<ImageGeneration pid="p" jobId="j" kind="style" records={[]} refresh={vi.fn()} onClose={vi.fn()}/>);
 expect(await screen.findByText(/业务图像调用最多1次.*物理网络尝试最多3次/)).toBeTruthy();
 expect(screen.queryByRole('combobox',{name:'未发出时额外技术重试次数'})).toBeNull();
 expect(screen.getByText(/第1次.*已确认未发出.*连接阶段/)).toBeTruthy();expect(screen.getByText(/第2次.*结果未知.*已开始响应.*响应体阶段/)).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'恢复原调用与登记'}));await waitFor(()=>expect(api).toHaveBeenCalledWith('/projects/p/image-jobs/j/recover',expect.anything()));
 expect(screen.getByText(/剩余1次/)).toBeTruthy();expect(screen.getByText(/恢复不会重置/)).toBeTruthy();
});
it('freezes a batch retry choice and shows business and physical limits before authorizing',async()=>{
 vi.mocked(api).mockImplementation(async(_path,options)=>options?.method?{id:'b',status:'preview',payload:{count:1,retry_policy:{version:1,max_not_sent_retries:4},call_limits:{images:2,vision:2,image_network_attempts:10}},jobs:[{...job,payload:{...job.payload,basis:{id:'pkg',version:1}},call:{...job.call,attempts:null}}]}:{items:[],next_start:null});
 render(<ImageBatches pid="p" packages={[pack]} records={[pack]} refresh={vi.fn()} onClose={vi.fn()}/>);
 setRetries(4);fireEvent.click(screen.getByRole('button',{name:'预览所选1格'}));
 expect(await screen.findByText(/业务图像调用最多2次.*物理网络尝试最多10次/)).toBeTruthy();
 expect(JSON.parse(String(vi.mocked(api).mock.calls.find(([,o])=>o?.method)?.[1]?.body)).max_not_sent_retries).toBe(4);
 expect(screen.queryByRole('combobox',{name:'未发出时额外技术重试次数'})).toBeNull();expect(screen.getByText(/没有逐次网络尝试证据/)).toBeTruthy();
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/start'))).toBe(false);
});
it('defaults batch retries to zero and uses a fresh submission token after changing a failed preview',async()=>{
 vi.mocked(api).mockImplementation(async(_path,options)=>{if(!options?.method)return {items:[],next_start:null};throw Error('批次预览失败');});
 render(<ImageBatches pid="p" packages={[pack]} records={[pack]} refresh={vi.fn()} onClose={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'预览所选1格'}));await screen.findByText('批次预览失败');
 const calls=()=>vi.mocked(api).mock.calls.filter(([,o])=>o?.method).map(([,o])=>JSON.parse(String(o?.body)));
 expect(calls()[0].max_not_sent_retries).toBe(0);
 setRetries(4);fireEvent.click(screen.getByRole('button',{name:'预览所选1格'}));await waitFor(()=>expect(calls()).toHaveLength(2));
 expect(calls()[1].max_not_sent_retries).toBe(4);expect(calls()[1].submission_id).not.toBe(calls()[0].submission_id);
});
it('keeps refusal and response evidence separate from unsent failures',async()=>{
 vi.mocked(api).mockResolvedValue({...job,status:'rejected',call:{...job.call,attempts:{max_attempts:5,remaining_attempts:3,attempts:[{sequence:1,evidence:{outcome:'received',response_started:true,transport_phase:'response_headers'}},{sequence:2,evidence:{outcome:'rejected',response_started:true,transport_phase:'response_body'}}]}}});
 render(<ImageGeneration pid="p" jobId="j" kind="style" records={[]} refresh={vi.fn()} onClose={vi.fn()}/>);
 expect(await screen.findByText(/第1次.*已收到响应.*已开始响应.*响应头阶段/)).toBeTruthy();expect(screen.getByText(/第2次.*供应商拒绝.*已开始响应.*响应体阶段/)).toBeTruthy();expect(screen.queryByRole('button',{name:'恢复原调用与登记'})).toBeNull();
});
