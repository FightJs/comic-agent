// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {useEffect} from 'react';
import {Images} from './Images';
import {api} from './api';
vi.mock('./api',async()=>({...await vi.importActual('./api'),api:vi.fn()}));
vi.mock('./DeliveryReadiness',()=>({DeliveryReadiness:()=>null}));
vi.mock('./Workflow',()=>({Conversation:()=>null,CandidateReview:()=>null}));
vi.mock('./AnnotationCanvas',()=>({AnnotationCanvas:({onState}:any)=>{useEffect(()=>onState([],true,7),[]);return <div>画布替身</div>;}}));
vi.mock('./ImageGeneration',()=>({ImageGeneration:({target,annotationEdit,onClose}:any)=><div role="dialog">固定编辑 {target.id} v{target.version} 批注v{annotationEdit.annotationVersion}<button onClick={onClose}>关闭编辑</button></div>}));
const image={id:'img',project_id:'p',kind:'image',title:'当前图',version:2,adopted:2,review:'approved',source:'manual',content:{url:'/image.png',episode:1,panel:1,batch:1},created:'',updated:''};
afterEach(()=>{cleanup();vi.resetAllMocks();localStorage.clear();});
it('opens explicit annotation edit with the saved server revision and current adopted image',async()=>{
 vi.mocked(api).mockImplementation(async(path)=>path.endsWith('/versions')?[image]:image);
 render(<Images {...{pid:'p',records:[image],episode:1,panel:1,batch:1,refresh:async()=>{},onSaved:()=>{},onPanel:()=>{},onLocation:()=>{}} as any}/>);
 const edit=await screen.findByRole('button',{name:'按批注编辑图片'});
 await waitFor(()=>expect((edit as HTMLButtonElement).disabled).toBe(false));
 fireEvent.click(edit);
 expect(screen.getByRole('dialog').textContent).toContain('固定编辑 img v2 批注v7');
 expect(vi.mocked(api).mock.calls.some(([,options])=>options?.method==='POST')).toBe(false);
 fireEvent.click(screen.getByRole('button',{name:'关闭编辑'}));
 expect(screen.queryByRole('dialog')).toBeNull();
});
it('blocks annotation edit while an unsaved local annotation draft exists',async()=>{
 localStorage.setItem('comic-annotations:img:2','draft');
 vi.mocked(api).mockImplementation(async(path)=>path.endsWith('/versions')?[image]:image);
 render(<Images {...{pid:'p',records:[image],episode:1,panel:1,batch:1,refresh:async()=>{},onSaved:()=>{},onPanel:()=>{},onLocation:()=>{}} as any}/>);
 expect((await screen.findByRole('button',{name:'按批注编辑图片'}) as HTMLButtonElement).disabled).toBe(true);
});
