// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ImageGeneration} from './ImageGeneration';
import {api} from './api';
vi.mock('./api',async()=>({...await vi.importActual('./api'),api:vi.fn()}));
HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
afterEach(()=>{cleanup();vi.resetAllMocks();localStorage.clear();});
const job={id:'j',status:'preview',payload:{title:'水墨',kind:'style',prompt:'水墨轮廓',input_refs:{},references:[]},call:{manifest:{provider:{model:'gpt-image-1.5'},parameters:{size:'1024x1536'},references:[],source:'ai'},result:null}};
it('requires a reviewed immutable preview before a paid start',async()=>{
 vi.mocked(api).mockImplementation(async(path,options)=>{if(!options?.method)return [];if(path.endsWith('/start'))return {...job,status:'blocked',error:'fixture'};return job;});
 render(<ImageGeneration pid="p" kind="style" records={[]} refresh={async()=>{}} onClose={()=>{}}/>);
 expect(screen.queryByRole('button',{name:'确认并生成1张'})).toBeNull();
 fireEvent.change(screen.getByLabelText('图片名称'),{target:{value:'水墨'}});
 fireEvent.change(screen.getByLabelText('完整生图提示词'),{target:{value:'水墨轮廓'}});
 fireEvent.click(screen.getByRole('button',{name:'预览模型与输入'}));
 expect(await screen.findByText('gpt-image-1.5')).toBeTruthy();
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/start'))).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'确认并生成1张'}));
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/start'))).toBe(true));
});
it('blocks authorization when an input still has unsaved edits',async()=>{
 vi.mocked(api).mockImplementation(async(_path,options)=>options?.method?{...job,payload:{...job.payload,input_refs:{asset:1}}}:[]);
 localStorage.setItem('comic-draft:p:asset','draft');
 render(<ImageGeneration pid="p" kind="style" records={[]} refresh={async()=>{}} onClose={()=>{}}/>);
 fireEvent.change(screen.getByLabelText('图片名称'),{target:{value:'水墨'}});fireEvent.change(screen.getByLabelText('完整生图提示词'),{target:{value:'轮廓'}});
 fireEvent.click(screen.getByRole('button',{name:'预览模型与输入'}));
 fireEvent.click(await screen.findByRole('button',{name:'确认并生成1张'}));
 expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('未保存'));
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/start'))).toBe(false);
});

it('allows stopping an inflight request even when a new local draft exists',async()=>{
 vi.mocked(api).mockImplementation(async(path,options)=>{if(!options?.method)return path.endsWith('/j')?{...job,status:'running'}:[];return {...job,status:path.endsWith('/cancel')?'cancelled':'running',payload:{...job.payload,input_refs:{asset:1}}};});
 render(<ImageGeneration pid="p" kind="style" records={[]} refresh={async()=>{}} onClose={()=>{}}/>);
 fireEvent.change(screen.getByLabelText('图片名称'),{target:{value:'水墨'}});fireEvent.change(screen.getByLabelText('完整生图提示词'),{target:{value:'轮廓'}});
 fireEvent.click(screen.getByRole('button',{name:'预览模型与输入'}));
 await screen.findByRole('button',{name:'停止后续写入'});
 localStorage.setItem('comic-draft:p:asset','new draft');
 fireEvent.click(screen.getByRole('button',{name:'停止后续写入'}));
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/cancel'))).toBe(true));
});

it('does not carry manual supplier confirmation into a different image call',async()=>{
 const first={...job,id:'old',status:'unknown'};
 vi.mocked(api).mockImplementation(async(_path,options)=>options?.method?{...job,id:'new',status:'unknown'}:[first]);
 render(<ImageGeneration pid="p" kind="style" records={[]} refresh={async()=>{}} onClose={()=>{}}/>);
 fireEvent.click(await screen.findByRole('button',{name:/水墨 · 供应商结果未知/}));
 fireEvent.click(screen.getByText('记录人工核对结论（不自动重试）'));
 fireEvent.change(screen.getByLabelText('核对依据'),{target:{value:'旧请求的核对依据'}});
 fireEvent.click(screen.getByLabelText('我已在供应商侧完成核对'));
 fireEvent.click(screen.getByRole('button',{name:'填写新要求'}));
 fireEvent.change(screen.getByLabelText('图片名称'),{target:{value:'另一个方向'}});fireEvent.change(screen.getByLabelText('完整生图提示词'),{target:{value:'轮廓'}});
 fireEvent.click(screen.getByRole('button',{name:'预览模型与输入'}));
 await screen.findByText(/水墨 · 供应商结果未知/);
 expect((screen.getByLabelText('我已在供应商侧完成核对') as HTMLInputElement).checked).toBe(false);
 expect((screen.getByLabelText('核对依据') as HTMLTextAreaElement).value).toBe('');
});

it('freezes package prompt and sends its version as the image basis',async()=>{
 const sent:any[]=[];
 vi.mocked(api).mockImplementation(async(_path,options)=>{if(!options?.method)return [];sent.push(JSON.parse(String(options.body)));return {...job,payload:{...job.payload,kind:'image',basis:{id:'pkg',version:5},image_content:{episode:7,panel:3}},call:job.call};});
 const basis={id:'pkg',project_id:'p',kind:'package',title:'第7话第3格',version:5,adopted:5,source:'manual',review:'pending',content:{episode:7,panel:3,prompt:'人工完整提示词'},created:'',updated:''};
 render(<ImageGeneration pid="p" kind="image" basis={basis} records={[basis]} refresh={async()=>{}} onClose={()=>{}}/>);
 expect((screen.getByLabelText('完整生图提示词') as HTMLTextAreaElement).readOnly).toBe(true);
 expect((screen.getByLabelText('完整生图提示词') as HTMLTextAreaElement).value).toBe('人工完整提示词');
 fireEvent.click(screen.getByRole('button',{name:'预览模型与输入'}));
 await waitFor(()=>expect(sent).toHaveLength(1));
 expect(sent[0]).toMatchObject({kind:'image',basis:{id:'pkg',version:5},prompt:'人工完整提示词',references:[]});
});
it('opens the exact batch job without offering a separate single-image authorization',async()=>{
 const managed={...job,payload:{...job.payload,kind:'image',image_batch_id:'batch',image_content:{episode:1,panel:1},basis:{id:'pkg',version:1}}};
 vi.mocked(api).mockImplementation(async(path)=>path.endsWith('/j')?managed:[]);
 render(<ImageGeneration pid="p" kind="image" jobId="j" basis={{id:'pkg',version:1,title:'固定包',content:{prompt:'固定提示',episode:1,panel:1}} as any} records={[]} refresh={async()=>{}} onClose={()=>{}}/>);
 expect(await screen.findByText('此单格由批次管理，启动或恢复请回到原批次；这里可核对结果、采用或记录人工结论。')).toBeTruthy();
 expect(screen.queryByRole('button',{name:'确认并生成1张'})).toBeNull();
 expect(screen.queryByRole('button',{name:'预览模型与输入'})).toBeNull();
});

it('blocks a saved style-test preview when its outline or novel has unsaved edits',async()=>{
 const fixed={...job,payload:{...job.payload,style_test:{basis:{outline:{id:'outline'},sources:[{record_id:'novel'}]}}}};
 vi.mocked(api).mockResolvedValue(fixed);
 render(<ImageGeneration pid="p" kind="style" jobId="j" records={[]} refresh={async()=>{}} onClose={()=>{}}/>);
 const start=await screen.findByRole('button',{name:'确认并生成1张'});
 localStorage.setItem('comic-draft:p:outline','unsaved after preview');fireEvent.click(start);
 expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('未保存'));
 expect(vi.mocked(api).mock.calls.some(([url])=>url.endsWith('/start'))).toBe(false);
});
