// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ImageGeneration} from './ImageGeneration';
import {api} from './api';
vi.mock('./api',async()=>({...await vi.importActual('./api'),api:vi.fn()}));
HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
afterEach(()=>{cleanup();vi.resetAllMocks();localStorage.clear();});
const target={id:'image',kind:'image',version:4,adopted:4,review:'approved',source:'manual',title:'雨夜原图',content:{url:'/synthetic.png',prompt:'旧的完整生图提示词',episode:1,panel:2}} as any;
const ref={id:'asset',kind:'asset',version:2,adopted:2,review:'approved',source:'manual',title:'人物参考',content:{url:'/reference.png'}} as any;
const basis={id:'package',kind:'package',version:8,title:'旧生图包',content:{prompt:'不应发送的包提示',episode:1,panel:2}} as any;
const job={id:'edit',status:'preview',payload:{kind:'image',title:'按批注调整雨夜',prompt:'缩小手中道具',target:{id:'image',version:4},annotation_edit:{annotation_version:7,preserve:'保留脸和服装'},references:[],input_refs:{image:4}},call:{manifest:{provider:{model:'synthetic-image'},parameters:{size:'1024x1536'},references:[{id:'image',version:4}],source:'ai'},attempts:null,result:null}};

it('previews an annotation edit with empty editable instructions, bound base, and additive references',async()=>{
 vi.mocked(api).mockImplementation(async(path,options)=>{if(!options?.method)return [];if(path.endsWith('/start'))return {...job,status:'blocked'};return job;});
 render(<ImageGeneration pid="p" kind="image" target={target} basis={basis} records={[target,ref,basis]} annotationEdit={{annotationVersion:7,preserve:'保留脸和服装'}} refresh={async()=>{}} onClose={()=>{}}/>);
 expect(screen.getByRole('heading',{name:'按批注编辑候选'})).toBeTruthy();
 const prompt=screen.getByLabelText('修改要求') as HTMLTextAreaElement;
 expect(prompt.value).toBe('');expect(prompt.readOnly).toBe(false);
 expect((screen.getByLabelText('保留要求') as HTMLTextAreaElement).value).toBe('保留脸和服装');
 expect(screen.getByText(/区域.*文字意图.*非硬蒙版/)).toBeTruthy();
 expect(screen.getByText(/不保证区域外像素锁定/)).toBeTruthy();
 const preview=screen.getByRole('button',{name:'预览按批注编辑'});
 expect(preview.hasAttribute('disabled')).toBe(true);
 fireEvent.change(prompt,{target:{value:'缩小手中道具'}});
 fireEvent.click(screen.getByLabelText(/人物参考/));
 fireEvent.click(preview);
 await screen.findByText('synthetic-image');
 const request=vi.mocked(api).mock.calls.find(([path,options])=>path.endsWith('/image-jobs')&&options?.method==='POST');
 const sent=JSON.parse(String(request?.[1]?.body));
 expect(sent).toMatchObject({kind:'image',target:{id:'image',version:4},prompt:'缩小手中道具',references:[{id:'asset',version:2}],annotation_edit:{annotation_version:7,preserve:'保留脸和服装'},max_not_sent_retries:0});
 expect(sent).not.toHaveProperty('basis');
 expect(vi.mocked(api).mock.calls.some(([path])=>path.endsWith('/start'))).toBe(false);
 expect(screen.getByText(/底图.*v4.*批注.*v7/)).toBeTruthy();
 expect(screen.queryByText(/生图包 v/)).toBeNull();
 fireEvent.click(screen.getByRole('button',{name:'确认并生成1张'}));
 await waitFor(()=>expect(vi.mocked(api).mock.calls.some(([path])=>path.endsWith('/start'))).toBe(true));
});

it('separates annotation history by target and hides annotation jobs from package generation',async()=>{
 const ordinary={...job,id:'ordinary',payload:{...job.payload,title:'包生成旧候选',annotation_edit:undefined,image_content:{episode:1,panel:2}}};
 const other={...job,id:'other',payload:{...job.payload,title:'其他底图编辑',target:{id:'other',version:1}}};
 vi.mocked(api).mockResolvedValue([job,ordinary,other]);
 const view=render(<ImageGeneration pid="p" kind="image" target={target} records={[target]} annotationEdit={{annotationVersion:7}} refresh={async()=>{}} onClose={()=>{}}/>);
 await screen.findByRole('button',{name:/按批注调整雨夜 · 待确认输入/});
 expect(screen.queryByRole('button',{name:/其他底图编辑/})).toBeNull();
 expect(screen.queryByRole('button',{name:/包生成旧候选/})).toBeNull();
 view.unmount();
 render(<ImageGeneration pid="p" kind="image" basis={basis} records={[basis]} refresh={async()=>{}} onClose={()=>{}}/>);
 await screen.findByRole('button',{name:/包生成旧候选/});
 expect(screen.queryByRole('button',{name:/按批注调整雨夜/})).toBeNull();
 expect(screen.queryByRole('button',{name:/其他底图编辑/})).toBeNull();
});

it('requires reopening when the bound image version changes instead of rebinding old annotations',async()=>{
 vi.mocked(api).mockResolvedValue([]);
 render(<ImageGeneration pid="p" kind="image" target={target} records={[{...target,version:5}]} annotationEdit={{annotationVersion:7}} refresh={async()=>{}} onClose={()=>{}}/>);
 fireEvent.change(screen.getByLabelText('修改要求'),{target:{value:'修正道具'}});
 expect(screen.getByText(/底图版本已变化.*重新打开/)).toBeTruthy();
 expect(screen.getByRole('button',{name:'预览按批注编辑'}).hasAttribute('disabled')).toBe(true);
});

it('keeps annotation instructions isolated from the previous normal generation draft',async()=>{
 vi.mocked(api).mockResolvedValue([]);
 const view=render(<ImageGeneration pid="p" kind="image" target={target} basis={basis} records={[target,basis]} refresh={async()=>{}} onClose={()=>{}}/>);
 expect((screen.getByLabelText('完整生图提示词') as HTMLTextAreaElement).value).toBe(basis.content.prompt);
 view.unmount();
 render(<ImageGeneration pid="p" kind="image" target={target} records={[target]} annotationEdit={{annotationVersion:7}} refresh={async()=>{}} onClose={()=>{}}/>);
 expect((screen.getByLabelText('修改要求') as HTMLTextAreaElement).value).toBe('');
});

it('blocks annotation preview when the fixed target has unsaved edits',async()=>{
 vi.mocked(api).mockResolvedValue([]);
 localStorage.setItem('comic-draft:p:image','synthetic unsaved target');
 render(<ImageGeneration pid="p" kind="image" target={target} records={[target]} annotationEdit={{annotationVersion:7}} refresh={async()=>{}} onClose={()=>{}}/>);
 fireEvent.change(screen.getByLabelText('修改要求'),{target:{value:'修正道具'}});
 fireEvent.click(screen.getByRole('button',{name:'预览按批注编辑'}));
 expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('未保存'));
 expect(vi.mocked(api).mock.calls.some(([,options])=>options?.method==='POST')).toBe(false);
});
