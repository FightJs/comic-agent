// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {VisionReviewButton} from './VisionReview';
import {api} from './api';
import {Drawer} from './ui';
vi.mock('./api',async()=>({...await vi.importActual('./api'),api:vi.fn()}));
HTMLDialogElement.prototype.showModal=function(){this.setAttribute('open','');};
HTMLDialogElement.prototype.close=function(){this.removeAttribute('open');};
afterEach(()=>{cleanup();vi.resetAllMocks();localStorage.clear();});
const target:any={id:'img',project_id:'p',kind:'image',title:'雨中重逢',version:2,adopted:2,source:'ai',review:'pending',content:{url:'/pixel.png'},created:'',updated:''};
const review:any={id:'r',status:'prepared',source:'ai',stale:false,manifest:{provider:{model:'vision-fixture'},images:[{id:'img',version:2,file_id:'f',width:16,height:24,source:'ai'}],descriptions:[{id:'img',title:'雨中重逢',version:2,prompt:'雨中'}],context:[]},raw:null,report:null,usage:null};
it('previews actual image inputs before explicit vision authorization and renders evidence',async()=>{
 const calls:string[]=[];
 vi.mocked(api).mockImplementation(async(path,opts)=>{calls.push(path);if(!opts?.method)return path.endsWith('/records')?[target]:[];return path.endsWith('/start')?{...review,status:'completed',report:{summary:'检查到发色偏差',issues:[{severity:'major',category:'identity',description:'头发颜色不同',evidence:'图1头顶为红色',images:[1],region:[.1,.1,.2,.2]}]}}:review;});
 render(<VisionReviewButton target={target}/>);
 fireEvent.click(screen.getByRole('button',{name:'模型视觉复查'}));
 fireEvent.click(await screen.findByRole('button',{name:'预览视觉检查范围'}));
 expect(await screen.findByText('vision-fixture')).toBeTruthy();
 expect(screen.getByRole('img',{name:'图1：雨中重逢'}).getAttribute('src')).toBe('/api/projects/p/files/f');
 expect(calls.some(p=>p.endsWith('/start'))).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'确认并检查1次'}));
 expect(await screen.findByText('头发颜色不同')).toBeTruthy();
 expect(screen.getByText('图1头顶为红色')).toBeTruthy();
 expect(screen.getByText(/不替代人工审核/)).toBeTruthy();
 expect(calls.some(p=>p.includes('/reviews/'))).toBe(false);
});
it('does not authorize from unsaved target or evidence drafts',async()=>{
 const scroll=vi.fn();HTMLElement.prototype.scrollIntoView=scroll;
 vi.mocked(api).mockImplementation(async(path,opts)=>opts?.method?review:path.endsWith('/records')?[target]:[]);
 render(<VisionReviewButton target={target}/>);fireEvent.click(screen.getByRole('button',{name:'模型视觉复查'}));
 fireEvent.click(await screen.findByRole('button',{name:'预览视觉检查范围'}));
 await screen.findByRole('button',{name:'确认并检查1次'});
 localStorage.setItem('comic-draft:p:img','draft');fireEvent.click(screen.getByRole('button',{name:'确认并检查1次'}));
 expect(await screen.findByRole('alert')).toHaveProperty('textContent',expect.stringContaining('未保存'));
 await waitFor(()=>expect(scroll).toHaveBeenCalled());
 expect(vi.mocked(api).mock.calls.some(([p])=>p.endsWith('/start'))).toBe(false);
});
it('updates the history row when a polled review finishes',async()=>{
 let started=false,polled=false;
 vi.mocked(api).mockImplementation(async(path,opts)=>{
  if(path.endsWith('/records'))return [target];
  if(path.endsWith('/start')){started=true;return {...review,status:'queued'};}
  if(path.endsWith('/r')&&!opts?.method){polled=true;return {...review,status:'completed'};}
  if(!opts?.method)return started?[{id:'r',target_version:2,status:polled?'completed':'queued',created:'2026-11-05'}]:[];
  return review;
 });
 render(<VisionReviewButton target={target}/>);fireEvent.click(screen.getByRole('button',{name:'模型视觉复查'}));
 fireEvent.click(await screen.findByRole('button',{name:'预览视觉检查范围'}));fireEvent.click(await screen.findByRole('button',{name:'确认并检查1次'}));
 await waitFor(()=>expect(screen.getByRole('button',{name:/目标v2 · 报告已保存/})).toBeTruthy(),{timeout:2200});
});

it('closes only the inner vision drawer on Escape',async()=>{
 vi.mocked(api).mockImplementation(async(path)=>path.endsWith('/records')?[target]:[]);
 const outerClose=vi.fn();
 render(<Drawer title="资产详情" onClose={outerClose}><VisionReviewButton target={target}/></Drawer>);
 fireEvent.click(screen.getByRole('button',{name:'模型视觉复查'}));
 const inner=await screen.findByRole('dialog',{name:'模型视觉复查'});
 fireEvent(inner,new Event('cancel',{bubbles:true,cancelable:true}));
 expect(outerClose).not.toHaveBeenCalled();
 expect(screen.getByRole('dialog',{name:'资产详情'})).toBeTruthy();
});
it('previews an exact original excerpt and sends only its immutable range',async()=>{
 const sent:any[]=[];const doc={id:'novel',title:'原著',parse_version:1,char_count:15,chapters:[],warnings:[]};
 const range={document_id:'novel',parse_version:1,start:7,end:14};
 vi.mocked(api).mockImplementation(async(path,opts)=>{
  if(path.endsWith('/records'))return [target];if(path.endsWith('/documents'))return [doc];
  if(path.includes('/documents/novel/text?'))return {text:'😀林秋穿红衣。',start:7,end:14};
  if(!opts?.method)return [];
  sent.push(JSON.parse(String(opts.body)));
  return {...review,manifest:{...review.manifest,sources:[{...range,title:'原著',quote:'😀林秋穿红衣。',head_parse_version:2,coverage:{complete:true}}],review_skills:[]}};
 });
 render(<VisionReviewButton target={target}/>);fireEvent.click(screen.getByRole('button',{name:'模型视觉复查'}));
 fireEvent.click(await screen.findByText('添加原著证据'));
 fireEvent.change(await screen.findByLabelText('原文起点'),{target:{value:'7'}});fireEvent.change(screen.getByLabelText('原文终点'),{target:{value:'14'}});
 fireEvent.click(screen.getByRole('button',{name:'读取这段原文'}));
 expect(await screen.findByText('😀林秋穿红衣。')).toBeTruthy();
 fireEvent.click(screen.getByRole('button',{name:'将这段加入检查'}));
 fireEvent.click(screen.getByRole('button',{name:'预览视觉检查范围'}));
 await waitFor(()=>expect(sent[0].source_ranges).toEqual([range]));
 expect(await screen.findByText(/原著 · 解析v1 · 7–14/)).toBeTruthy();
 expect(screen.getByText(/此段来自历史解析版本/)).toBeTruthy();
});
it('does not reintroduce an old excerpt after the user changes its range during reading',async()=>{
 let reply!:(value:any)=>void;
 const pending=new Promise(resolve=>{reply=resolve;});
 vi.mocked(api).mockImplementation(async(path)=>{
  if(path.endsWith('/records'))return [target];if(path.endsWith('/documents'))return [{id:'novel',title:'原著',parse_version:1,char_count:15,chapters:[],warnings:[]}];
  if(path.includes('/documents/novel/text?'))return pending;return [];
 });
 render(<VisionReviewButton target={target}/>);fireEvent.click(screen.getByRole('button',{name:'模型视觉复查'}));fireEvent.click(await screen.findByText('添加原著证据'));
 fireEvent.change(await screen.findByLabelText('原文起点'),{target:{value:'7'}});fireEvent.change(screen.getByLabelText('原文终点'),{target:{value:'14'}});
 fireEvent.click(screen.getByRole('button',{name:'读取这段原文'}));
 fireEvent.change(screen.getByLabelText('原文起点'),{target:{value:'8'}});
 reply({text:'😀林秋穿红衣。',start:7,end:14});
 await waitFor(()=>expect(screen.getByRole('button',{name:'读取这段原文'})).toHaveProperty('disabled',false));
 expect(screen.queryByRole('button',{name:'将这段加入检查'})).toBeNull();
});

it('opens an exact managed batch report without showing new-call or recovery controls',async()=>{
 const {VisionReview}=await import('./VisionReview');
 vi.mocked(api).mockImplementation(async(path)=>path.endsWith('/r')?{...review,manifest:{...review.manifest,image_batch_id:'batch'}}:path.endsWith('/records')?[target]:[]);
 render(<VisionReview target={target} reviewId="r" onClose={()=>{}}/>);
 expect(await screen.findByText(/固定批次检查记录，只读查看/)).toBeTruthy();await screen.findByText('vision-fixture');
 expect(screen.queryByRole('button',{name:'确认并检查1次'})).toBeNull();expect(screen.queryByRole('button',{name:'重新选择检查范围'})).toBeNull();
 expect(vi.mocked(api).mock.calls.every(([,opts])=>!opts?.method)).toBe(true);
});
